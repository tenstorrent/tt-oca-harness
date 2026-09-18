// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// DMA Frontend
//
//-----------------------------------------------------------------------------


module idma_frontend_wrapper #(
  parameter int unsigned NUM_CTRL_INTERFACES = 1,  // must be >= 1
  parameter int unsigned NUM_CTRL_STREAMS = 1, // must be >= 1

  parameter int unsigned F2M_FIFO_DEPTH = 4,    // minimum depth of 1, any value set here will create a depth of 1 + val

  parameter bit BYPASS_DMA_CTRL_FLOPS = 1'b0,

  parameter int unsigned NumDim = 2,
  parameter int unsigned RepWidth = 32,

  parameter type idma_req_t = logic,
  parameter type idma_resp_t = logic,
  parameter type idma_nd_req_t = logic,
  parameter type dma_mst_addr_t = logic,

  // AXI ctrl interface types
  parameter type dma_ctrl_req_t  = logic,
  parameter type dma_ctrl_resp_t = logic,

  // Width params for internal AXI typedef + axi_to_reg_v2
  parameter int unsigned CTRL_ADDR_WIDTH = 9,
  parameter int unsigned CTRL_DATA_WIDTH = 64,
  parameter int unsigned CTRL_ID_WIDTH   = 8,
  parameter int unsigned CTRL_USER_WIDTH = 12
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_en_i,

  output logic dma_frontend_wakeup_o,
  output logic dma_frontend_busy_o,

  // AXI interface to DMA control registers
  input  dma_ctrl_req_t  [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_req_i,
  output dma_ctrl_resp_t [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_resp_o,

  // iDMA request/response interface
  output idma_req_t  [NUM_CTRL_INTERFACES-1:0] req_o,
  output logic       [NUM_CTRL_INTERFACES-1:0] req_valid_o,
  input  logic       [NUM_CTRL_INTERFACES-1:0] req_ready_i,

  input  idma_resp_t [NUM_CTRL_INTERFACES-1:0] resp_i,
  input  logic       [NUM_CTRL_INTERFACES-1:0] resp_valid_i,
  output logic       [NUM_CTRL_INTERFACES-1:0] resp_ready_o
);

  `include "axi/typedef.svh"
  `include "register_interface/typedef.svh"

  /////////////
  // Defines //
  /////////////

  // define local parameter for internal data width of axi reg interface
  localparam int unsigned DMA_CTRL_REG_DATA_W = 32;
  localparam int unsigned DMA_CTRL_REG_STRB_W = DMA_CTRL_REG_DATA_W / 8;

  typedef logic [DMA_CTRL_REG_DATA_W-1:0] reg_data_t;
  typedef logic [DMA_CTRL_REG_STRB_W-1:0] reg_strb_t;

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

  // define AXI req/resp interface
  slv_axi_req_t [NUM_CTRL_INTERFACES-1:0] slv_axi_reqs_flopped;
  slv_axi_resp_t [NUM_CTRL_INTERFACES-1:0] slv_axi_resps_flopped;

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

  generate
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
      ) dma_ctrl_axi_cut (
        .clk_i     (clk_i),
        .rst_ni    (rst_ni),
        .slv_req_i (dma_ctrl_axi_req_i[i]),
        .slv_resp_o(dma_ctrl_axi_resp_o[i]),
        .mst_req_o (slv_axi_reqs_flopped[i]),
        .mst_resp_i(slv_axi_resps_flopped[i])
      );

      // Downsize (if needed) and convert AXI ctrl interface to PULP register ctrl interface
      axi_to_reg_v2 #(
        .AxiAddrWidth(CTRL_ADDR_WIDTH),
        .AxiDataWidth(CTRL_DATA_WIDTH),
        .AxiIdWidth  (CTRL_ID_WIDTH),
        .AxiUserWidth(CTRL_USER_WIDTH),
        .RegDataWidth(DMA_CTRL_REG_DATA_W),
        .axi_req_t   (slv_axi_req_t),
        .axi_rsp_t   (slv_axi_resp_t),
        .reg_req_t   (reg_req_t),
        .reg_rsp_t   (reg_resp_t)
      ) axi_to_reg (
        .clk_i (clk_i),
        .rst_ni(rst_ni),

        .axi_req_i(slv_axi_reqs_flopped[i]),
        .axi_rsp_o(slv_axi_resps_flopped[i]),
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
      ) iDMA_frontend (
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
      ) idma_transfer_id_gen (
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
      ) F2M_request_fifo (
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
        .NumDim       (NumDim),
        .addr_t       (dma_mst_addr_t),
        .idma_req_t   (idma_req_t),
        .idma_rsp_t   (idma_resp_t),
        .idma_nd_req_t(idma_nd_req_t),
        .RepWidths    ({RepWidth, RepWidth})
      ) iDMA_2d_midend (
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
  endgenerate

  assign req_o = me_req;
  assign req_valid_o = me_req_valid;
  assign me_req_ready = req_ready_i;

  assign me_resp = resp_i;
  assign me_resp_valid = resp_valid_i;
  assign resp_ready_o = me_resp_ready;

  assign dma_frontend_wakeup_o = (|fe_busy) | (|f2m_req_valid) | (|me_busy);
  assign dma_frontend_busy_o =(|f2m_req_valid) | (|me_busy);

endmodule
