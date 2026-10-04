// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Accept AXI control traffic in an iDMA register frontend and emit 1-D iDMA requests.
//
// Each control interface has its own chain: an axi_cut, an axi_dw_converter to 32-bit AXI, an
// axi_to_reg_v2 bridge to a 32-bit register interface, the idma_reg64_2d register frontend, a
// stream_fifo that buffers 2-D requests between the register frontend and the 2-D midend, and
// an idma_nd_midend that splits each 2-D request into 1-D requests. An idma_transfer_id_gen per interface issues transfer IDs
// and retires one on each midend completion. NUM_CTRL_INTERFACES and NUM_CTRL_STREAMS must be
// >= 1. F2M_FIFO_DEPTH is passed unchanged to the stream_fifo DEPTH and is the FIFO depth in
// requests; fifo_v3 asserts DEPTH > 0.

module idma_frontend_wrapper #(
  parameter int unsigned NUM_CTRL_INTERFACES = 1,           // Independent control ports, each with
                                                            // its own frontend, FIFO and midend;
                                                            // must be >= 1.
  parameter int unsigned NUM_CTRL_STREAMS = 1,              // Register-frontend streams per control
                                                            // port; must be >= 1. The stream index
                                                            // is unconnected, so all streams share
                                                            // one FIFO and midend.

  parameter int unsigned F2M_FIFO_DEPTH = 4,                // Depth in requests of the FIFO between
                                                            // the register frontend and the 2-D
                                                            // midend; passed unchanged to
                                                            // stream_fifo DEPTH and must be > 0.

  parameter bit BYPASS_DMA_CTRL_FLOPS = 1'b0,               // When set, the control-port axi_cut is
                                                            // a pass-through with no registers.

  parameter int unsigned NUM_DIM = 2,                       // Transfer dimension count of the
                                                            // midend; the 2-D register frontend and
                                                            // two-entry RepWidths match only 2.
  parameter int unsigned REP_WIDTH = 32,                    // Width of each midend repetition
                                                            // counter.

  parameter type idma_req_t = logic,                        // 1-D iDMA request type emitted by the
                                                            // midend.
  parameter type idma_resp_t = logic,                       // iDMA response type returned by the
                                                            // backend.
  parameter type idma_nd_req_t = logic,                     // 2-D request type produced by the
                                                            // register frontend.
  parameter type dma_mst_addr_t = logic,                    // Transfer address type used by the
                                                            // midend.

  parameter type dma_ctrl_req_t  = logic,                   // AXI ctrl request type.
  parameter type dma_ctrl_resp_t = logic,                   // AXI ctrl response type.

  parameter int unsigned CTRL_ADDR_WIDTH = 9,               // Ctrl AXI address width.
  parameter int unsigned CTRL_DATA_WIDTH = 64,              // Ctrl AXI data width; must be >= 32.
                                                            // axi_dw_converter narrows it to the
                                                            // 32-bit register width.
  parameter int unsigned CTRL_ID_WIDTH   = 8,               // Ctrl AXI ID width.
  parameter int unsigned CTRL_USER_WIDTH = 12               // Ctrl AXI user width.
) (
  input  logic clk_i,                                       // Frontend clock; the gated frontend
                                                            // clock in idma_wrapper.
  input  logic rst_ni,                                      // Async reset, active-low.
  input  logic test_en_i,                                   // Test mode, driven to the request FIFO
                                                            // testmode input.

  output logic dma_frontend_wakeup_o,                       // High while any interface has an AXI
                                                            // control command in flight, a queued
                                                            // request, or a busy midend.
  output logic dma_frontend_busy_o,                         // High while any request FIFO is
                                                            // non-empty or any midend is busy;
                                                            // in-flight AXI control commands are
                                                            // excluded.

  input  dma_ctrl_req_t  [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_req_i, // AXI control subordinate request per interface.
  output dma_ctrl_resp_t [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_resp_o, // AXI control subordinate response per interface.

  output idma_req_t  [NUM_CTRL_INTERFACES-1:0] req_o,       // 1-D request from each midend.
  output logic       [NUM_CTRL_INTERFACES-1:0] req_valid_o, // Outbound request valid.
  input  logic       [NUM_CTRL_INTERFACES-1:0] req_ready_i, // Outbound request ready.

  input  idma_resp_t [NUM_CTRL_INTERFACES-1:0] resp_i,      // 1-D response to each midend.
  input  logic       [NUM_CTRL_INTERFACES-1:0] resp_valid_i, // Response valid; a response with last
                                                             // set completes the 2-D transfer and
                                                             // retires its ID.
  output logic       [NUM_CTRL_INTERFACES-1:0] resp_ready_o // Midend ready for the backend
                                                            // response.
);

  `include "axi/typedef.svh"
  `include "register_interface/typedef.svh"

  /////////////
  // Defines //
  /////////////

  // define local parameter for internal data width of axi reg interface
  localparam int unsigned DmaCtrlRegDataW = 32;
  localparam int unsigned DmaCtrlRegStrbW = DmaCtrlRegDataW / 8;

  typedef logic [DmaCtrlRegDataW-1:0] reg_data_t;
  typedef logic [DmaCtrlRegStrbW-1:0] reg_strb_t;

  /////////////////////////////////////////
  // Setup iDMA Control Typedefs/Structs //
  /////////////////////////////////////////

  // Local type derivations from width parameters
  typedef logic [CTRL_ADDR_WIDTH-1:0] ctrl_addr_t;
  typedef logic [CTRL_ID_WIDTH-1:0] ctrl_id_t;
  typedef logic [CTRL_DATA_WIDTH-1:0] ctrl_data_t;
  typedef logic [CTRL_DATA_WIDTH/8-1:0] ctrl_strb_t;
  typedef logic [CTRL_USER_WIDTH-1:0] ctrl_user_t;

  // setup channel types for slave AXI interfaces
  `AXI_TYPEDEF_ALL(slv_axi, ctrl_addr_t, ctrl_id_t, ctrl_data_t, ctrl_strb_t, ctrl_user_t)
  `AXI_TYPEDEF_ALL(reg_axi, ctrl_addr_t, ctrl_id_t, reg_data_t, reg_strb_t, ctrl_user_t)

  // define AXI req/resp interface
  slv_axi_req_t [NUM_CTRL_INTERFACES-1:0] slv_axi_reqs_flopped;
  slv_axi_resp_t [NUM_CTRL_INTERFACES-1:0] slv_axi_resps_flopped;
  reg_axi_req_t [NUM_CTRL_INTERFACES-1:0] reg_axi_reqs;
  reg_axi_resp_t [NUM_CTRL_INTERFACES-1:0] reg_axi_resps;

  // setup channel types for REG interface
  `REG_BUS_TYPEDEF_REQ(reg_req_t, ctrl_addr_t, reg_data_t, reg_strb_t)
  `REG_BUS_TYPEDEF_RSP(reg_resp_t, reg_data_t)

  // define REG req/resp interface
  reg_req_t  [NUM_CTRL_INTERFACES-1:0] reg_reqs;
  reg_resp_t [NUM_CTRL_INTERFACES-1:0] reg_resps;

  // define iDMA frontend signals
  idma_nd_req_t [NUM_CTRL_INTERFACES-1:0] fe_nd_req;
  logic [NUM_CTRL_INTERFACES-1:0] fe_req_valid, fe_req_ready;

  // frontend tracking of total dma transactions
  logic [NUM_CTRL_INTERFACES-1:0][31:0] next_id, done_id;

  // frontend command fifo to nd midend
  idma_nd_req_t [NUM_CTRL_INTERFACES-1:0] f2m_req;
  logic [NUM_CTRL_INTERFACES-1:0] f2m_req_valid, f2m_req_ready;

  // midend signals
  idma_req_t [NUM_CTRL_INTERFACES-1:0] me_req;
  logic [NUM_CTRL_INTERFACES-1:0] me_req_valid, me_req_ready;

  idma_resp_t [NUM_CTRL_INTERFACES-1:0] me_resp;
  logic [NUM_CTRL_INTERFACES-1:0] me_resp_valid, me_resp_ready;

  // midend return path for complete commands
  logic [NUM_CTRL_INTERFACES-1:0] trans_complete;

  // status signals
  logic [NUM_CTRL_INTERFACES-1:0] fe_busy;
  logic [NUM_CTRL_INTERFACES-1:0] me_busy;

  //////////////////
  // DMA Frontend //
  //////////////////

  for (genvar i = 0; i < NUM_CTRL_INTERFACES; i = i + 1) begin : gen_axi_to_iDMA_fe
    // add spill register to all axi interface (helps with timing)
    // setting bypass will remove registers
    axi_cut #(
      .Bypass    (BYPASS_DMA_CTRL_FLOPS),
      .aw_chan_t (slv_axi_aw_chan_t),
      .w_chan_t  (slv_axi_w_chan_t),
      .b_chan_t  (slv_axi_b_chan_t),
      .ar_chan_t (slv_axi_ar_chan_t),
      .r_chan_t  (slv_axi_r_chan_t),
      .axi_req_t (slv_axi_req_t),
      .axi_resp_t(slv_axi_resp_t)
    ) u_dma_ctrl_axi_cut (
      .clk_i     (clk_i),
      .rst_ni    (rst_ni),
      .slv_req_i (dma_ctrl_axi_req_i[i]),
      .slv_resp_o(dma_ctrl_axi_resp_o[i]),
      .mst_req_o (slv_axi_reqs_flopped[i]),
      .mst_resp_i(slv_axi_resps_flopped[i])
    );

    // axi_to_reg_v2 reads every 32-bit half of a wider beat whatever the AXI size, and a read
    // of NEXT_ID_0 launches a transfer. Narrowing to the register width first keeps a 32-bit
    // read of the other half of NEXT_ID_0's word off NEXT_ID_0.
    axi_dw_converter #(
      .AxiMaxReads        (1),
      .AxiSlvPortDataWidth(CTRL_DATA_WIDTH),
      .AxiMstPortDataWidth(DmaCtrlRegDataW),
      .AxiAddrWidth       (CTRL_ADDR_WIDTH),
      .AxiIdWidth         (CTRL_ID_WIDTH),
      .aw_chan_t          (slv_axi_aw_chan_t),
      .mst_w_chan_t       (reg_axi_w_chan_t),
      .slv_w_chan_t       (slv_axi_w_chan_t),
      .b_chan_t           (slv_axi_b_chan_t),
      .ar_chan_t          (slv_axi_ar_chan_t),
      .mst_r_chan_t       (reg_axi_r_chan_t),
      .slv_r_chan_t       (slv_axi_r_chan_t),
      .axi_mst_req_t      (reg_axi_req_t),
      .axi_mst_resp_t     (reg_axi_resp_t),
      .axi_slv_req_t      (slv_axi_req_t),
      .axi_slv_resp_t     (slv_axi_resp_t)
    ) u_dma_ctrl_dw_converter (
      .clk_i     (clk_i),
      .rst_ni    (rst_ni),
      .slv_req_i (slv_axi_reqs_flopped[i]),
      .slv_resp_o(slv_axi_resps_flopped[i]),
      .mst_req_o (reg_axi_reqs[i]),
      .mst_resp_i(reg_axi_resps[i])
    );

    axi_to_reg_v2 #(
      .AxiAddrWidth(CTRL_ADDR_WIDTH),
      .AxiDataWidth(DmaCtrlRegDataW),
      .AxiIdWidth  (CTRL_ID_WIDTH),
      .AxiUserWidth(CTRL_USER_WIDTH),
      .RegDataWidth(DmaCtrlRegDataW),
      .axi_req_t   (reg_axi_req_t),
      .axi_rsp_t   (reg_axi_resp_t),
      .reg_req_t   (reg_req_t),
      .reg_rsp_t   (reg_resp_t)
    ) u_axi_to_reg (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .axi_req_i(reg_axi_reqs[i]),
      .axi_rsp_o(reg_axi_resps[i]),
      .reg_req_o(reg_reqs[i]),
      .reg_rsp_i(reg_resps[i]),
      .reg_id_o (/* NOT CONNECTED */),

      .busy_o(fe_busy[i])  // busy when there is an inflight AXI command
    );

    // ----------
    // Frontend
    // ----------
    idma_reg64_2d #(
      .NumRegs       (1),   // one reg interface
      .NumStreams    (NUM_CTRL_STREAMS),
      .IdCounterWidth(32),  // next_id counter is 32 bits wide
      .reg_req_t     (reg_req_t),
      .reg_rsp_t     (reg_resp_t),
      .dma_req_t     (idma_nd_req_t)
    ) u_iDMA_frontend (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .dma_ctrl_req_i(reg_reqs[i]),
      .dma_ctrl_rsp_o(reg_resps[i]),

      .dma_req_o   (fe_nd_req[i]),
      .req_valid_o (fe_req_valid[i]),
      .req_ready_i (fe_req_ready[i]),
      .next_id_i   (next_id[i]),
      .stream_idx_o(/*NOT CONNECTED*/),  // can be ignored since only 1 stream

      .busy_i({8{fe_req_ready[i]}}), // instead of checking if backend is busy, just check if another command can be issued
      .midend_busy_i(me_busy[i]),
      .done_id_i(done_id[i])
    );

    idma_transfer_id_gen #(
      .IdWidth(32)  // next_id counter is 32 bits wide
    ) u_idma_transfer_id_gen (
      .clk_i        (clk_i),
      .rst_ni       (rst_ni),
      .issue_i      (fe_req_valid[i] && fe_req_ready[i]),
      .retire_i     (trans_complete[i]),
      .next_o       (next_id[i]),
      .completed_o  (done_id[i])
    );

    // ----------
    // Midend
    // ----------
    // add a fifo to buffer requests
    stream_fifo #(
      .DEPTH(F2M_FIFO_DEPTH),
      .T    (idma_nd_req_t)
    ) u_F2M_request_fifo (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .flush_i   (1'b0),
      .testmode_i(test_en_i),
      .usage_o   (/*NOT CONNECTED*/),

      .data_i (fe_nd_req[i]),
      .valid_i(fe_req_valid[i]),
      .ready_o(fe_req_ready[i]),

      .data_o (f2m_req[i]),
      .valid_o(f2m_req_valid[i]),
      .ready_i(f2m_req_ready[i])
    );

    idma_nd_midend #(
      .NumDim       (NUM_DIM),
      .addr_t       (dma_mst_addr_t),
      .idma_req_t   (idma_req_t),
      .idma_rsp_t   (idma_resp_t),
      .idma_nd_req_t(idma_nd_req_t),
      .RepWidths    ({REP_WIDTH, REP_WIDTH})
    ) u_iDMA_2d_midend (
      .clk_i (clk_i),
      .rst_ni(rst_ni),

      .nd_req_i      (f2m_req[i]),
      .nd_req_valid_i(f2m_req_valid[i]),
      .nd_req_ready_o(f2m_req_ready[i]),

      .nd_rsp_o      (/*NOT CONNECTED*/), // no need to send any rsp data, valid is enough to signify completion
      .nd_rsp_valid_o(trans_complete[i]),
      .nd_rsp_ready_i(1'b1),  // Always ready to accept completed transfers

      .burst_req_o      (me_req[i]),
      .burst_req_valid_o(me_req_valid[i]),
      .burst_req_ready_i(me_req_ready[i]),

      .burst_rsp_i      (me_resp[i]),
      .burst_rsp_valid_i(me_resp_valid[i]),
      .burst_rsp_ready_o(me_resp_ready[i]),

      .busy_o(me_busy[i])
    );
  end

  assign req_o = me_req;
  assign req_valid_o = me_req_valid;
  assign me_req_ready = req_ready_i;

  assign me_resp = resp_i;
  assign me_resp_valid = resp_valid_i;
  assign resp_ready_o = me_resp_ready;

  assign dma_frontend_wakeup_o = (|fe_busy) | (|f2m_req_valid) | (|me_busy);
  assign dma_frontend_busy_o =(|f2m_req_valid) | (|me_busy);

endmodule
