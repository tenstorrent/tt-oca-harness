// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Turn 1-D iDMA transfer requests into AXI master read and write traffic.
//
// Each master interface has its own idma_backend_rw_axi with a hardware legalizer, zero-length
// rejection and no error handling; an axi_mux merges its read and write ports and an axi_cut
// registers the master port.
// NUM_MST_INTERFACES must be >= 1.
// BUFFER_DEPTH is the realignment buffer depth in beats and must be >= 2; 3 handles misaligned
// transfers efficiently.
// EN_R_AW_COUPLING is recommended.

module idma_backend_wrapper #(
  parameter int unsigned NUM_MST_INTERFACES = 1,            // Backend master count; must be >= 1.

  parameter int unsigned DMA_MST_MAX_TXNS = 16,             // Max outstanding AXI transactions per
                                                            // master interface.

  parameter int unsigned M2B_FIFO_DEPTH = 0,                // Depth of the request FIFO ahead of
                                                            // each backend; 0 passes requests
                                                            // straight through.
  parameter int unsigned BUFFER_DEPTH = 3,                  // Realignment buffer depth in beats;
                                                            // must be >= 2.

  parameter bit EN_R_AW_COUPLING = 1,                       // Makes the backend's R-to-AW coupling
                                                            // hardware available; recommended.

  parameter bit BYPASS_DMA_MST_FLOPS  = 1'b0,               // Bypasses the axi_cut registers on
                                                            // each master port.

  parameter int unsigned TF_LEN_WIDTH = 32,                 // Transfer-length field width; the
                                                            // maximum transfer is 2**TF_LEN_WIDTH
                                                            // bytes.

  parameter type idma_req_t = logic,                        // iDMA request type.
  parameter type idma_resp_t = logic,                       // iDMA response type.

  parameter type dma_mst_req_t  = logic,                    // AXI master request type.
  parameter type dma_mst_resp_t = logic,                    // AXI master response type.

  parameter int unsigned AXI_ADDR_WIDTH       = 56,         // AXI address width.
  parameter int unsigned AXI_DATA_WIDTH       = 64,         // Data width of the AXI master port and
                                                            // the backend transfer buffer.
  parameter int unsigned AXI_USER_WIDTH       = 12,         // User-signal width of the AXI master
                                                            // port.
  parameter int unsigned MST_ID_WIDTH         = 3,          // AXI master ID width; must equal
                                                            // BACKEND_INT_ID_WIDTH + 1.
  parameter int unsigned BACKEND_INT_ID_WIDTH = 2           // ID width of idma_req_t and of the
                                                            // backend read and write ports; axi_mux
                                                            // widens it by one bit.
) (
  input  logic clk_i,                                       // System clock.
  input  logic rst_ni,                                      // Async reset, active-low.
  input  logic test_en_i,                                   // DFT test enable for the request FIFO,
                                                            // the backend and the AXI mux.

  output logic dma_backend_busy_o,                          // High while any request is pending,
                                                            // any backend is busy, or any AW awaits
                                                            // its B or AR its last R.

  input  idma_req_t  [NUM_MST_INTERFACES-1:0] req_i,        // Backend request payload.
  input  logic       [NUM_MST_INTERFACES-1:0] req_valid_i,  // Backend request valid.
  output logic       [NUM_MST_INTERFACES-1:0] req_ready_o,  // Backend request ready.

  output idma_resp_t [NUM_MST_INTERFACES-1:0] resp_o,       // Backend response payload.
  output logic       [NUM_MST_INTERFACES-1:0] resp_valid_o, // Backend response valid.
  input  logic       [NUM_MST_INTERFACES-1:0] resp_ready_i, // Backend response ready.

  output dma_mst_req_t  [NUM_MST_INTERFACES-1:0] dma_mst_axi_req_o, // AXI master request, registered by axi_cut unless BYPASS_DMA_MST_FLOPS.
  input  dma_mst_resp_t [NUM_MST_INTERFACES-1:0] dma_mst_axi_resp_i // AXI master response.
);

  `include "ocah_assert.svh"
  `include "axi/typedef.svh"

  `OCAH_ASSERT_STATIC(MstIdWidth_A, MST_ID_WIDTH == BACKEND_INT_ID_WIDTH + 1,
                      "MST_ID_WIDTH must be one more than the backend's internal ID width")
  `OCAH_ASSERT_STATIC(ReqIdWidth_A, $bits(req_i[0].opt.axi_id) == BACKEND_INT_ID_WIDTH,
                      "req_i opt.axi_id must be the backend's internal ID width")

  /////////////////////////////////////////
  // Setup iDMA Control Typedefs/Structs //
  /////////////////////////////////////////

  // Local type derivations from width parameters
  typedef logic [AXI_ADDR_WIDTH-1:0] axi_addr_t;
  typedef logic [AXI_DATA_WIDTH-1:0] axi_data_t;
  typedef logic [AXI_DATA_WIDTH/8-1:0] axi_strb_t;
  typedef logic [AXI_USER_WIDTH-1:0] axi_user_t;
  typedef logic [MST_ID_WIDTH-1:0] mst_id_t;
  typedef logic [BACKEND_INT_ID_WIDTH-1:0] int_mst_id_t;

  // setup channel types for internal AXI output
  `AXI_TYPEDEF_ALL(int_axi, axi_addr_t, int_mst_id_t, axi_data_t, axi_strb_t, axi_user_t)
  // setup channel types for master AXI output
  `AXI_TYPEDEF_ALL(mst_axi, axi_addr_t, mst_id_t, axi_data_t, axi_strb_t, axi_user_t)

  typedef struct packed {int_axi_ar_chan_t ar_chan;} axi_read_meta_channel_t;

  typedef struct packed {axi_read_meta_channel_t axi;} read_meta_channel_t;

  typedef struct packed {int_axi_aw_chan_t aw_chan;} axi_write_meta_channel_t;

  typedef struct packed {axi_write_meta_channel_t axi;} write_meta_channel_t;

  // define internal AXI interface
  int_axi_req_t [NUM_MST_INTERFACES-1:0] int_axi_read_req;
  int_axi_req_t [NUM_MST_INTERFACES-1:0] int_axi_write_req;
  int_axi_resp_t [NUM_MST_INTERFACES-1:0] int_axi_read_resp;
  int_axi_resp_t [NUM_MST_INTERFACES-1:0] int_axi_write_resp;

  // define master AXI interface
  mst_axi_req_t [NUM_MST_INTERFACES-1:0] mst_axi_req;
  mst_axi_resp_t [NUM_MST_INTERFACES-1:0] mst_axi_resp;

  // backend signals
  idma_req_t [NUM_MST_INTERFACES-1:0] be_req;
  logic [NUM_MST_INTERFACES-1:0] be_req_valid, be_req_ready;

  idma_pkg::idma_busy_t [NUM_MST_INTERFACES-1:0] be_busy;

  /////////////////
  // DMA Backend //
  /////////////////

  for (genvar i = 0; i < NUM_MST_INTERFACES; i = i + 1) begin : gen_iDMA_to_axi_out
    // add a fifo to buffer requests
    if (M2B_FIFO_DEPTH == 0) begin : gen_M2B_passthrough
      assign be_req[i] = req_i[i];
      assign be_req_valid[i] = req_valid_i[i];
      assign req_ready_o[i] = be_req_ready[i];
    end else begin : gen_M2B_fifo
      stream_fifo #(
        .DEPTH(M2B_FIFO_DEPTH),
        .T    (idma_req_t)
      ) u_M2B_request_fifo (
        .clk_i     (clk_i),
        .rst_ni    (rst_ni),
        .flush_i   (1'b0),
        .testmode_i(test_en_i),
        .usage_o   (/*NOT CONNECTED*/),

        .data_i (req_i[i]),
        .valid_i(req_valid_i[i]),
        .ready_o(req_ready_o[i]),

        .data_o (be_req[i]),
        .valid_o(be_req_valid[i]),
        .ready_i(be_req_ready[i])
      );
    end

    // ----------
    // Backend
    // ----------
    idma_backend_rw_axi #(
      .DataWidth(AXI_DATA_WIDTH),
      .AddrWidth(AXI_ADDR_WIDTH),
      .UserWidth(AXI_USER_WIDTH),
      .AxiIdWidth(BACKEND_INT_ID_WIDTH),
      .NumAxInFlight(DMA_MST_MAX_TXNS),
      .BufferDepth(BUFFER_DEPTH),
      .TFLenWidth(TF_LEN_WIDTH),
      .MemSysDepth(32'd0),  // not attached to a memory system
      .RAWCouplingAvail(EN_R_AW_COUPLING),
      .MaskInvalidData(1'b1),  // data with no wstrb is masked to 0
      .HardwareLegalizer(1'b1),  // add hardware legalizer (checks if it's AXI4-conformal)
      .RejectZeroTransfers(1'b1),  // reject invalid (zero) length transfers
      .ErrorCap(idma_pkg::NO_ERROR_HANDLING),
      .idma_req_t(idma_req_t),
      .idma_rsp_t(idma_resp_t),
      .idma_eh_req_t(idma_pkg::idma_eh_req_t),
      .idma_busy_t(idma_pkg::idma_busy_t),
      .axi_req_t(int_axi_req_t),
      .axi_rsp_t(int_axi_resp_t),
      .write_meta_channel_t(write_meta_channel_t),
      .read_meta_channel_t(read_meta_channel_t)
    ) u_iDMA_backend (
      .clk_i     (clk_i),
      .rst_ni    (rst_ni),
      .testmode_i(test_en_i),

      .idma_req_i (be_req[i]),
      .req_valid_i(be_req_valid[i]),
      .req_ready_o(be_req_ready[i]),

      .idma_rsp_o (resp_o[i]),
      .rsp_valid_o(resp_valid_o[i]),
      .rsp_ready_i(resp_ready_i[i]),

      .idma_eh_req_i ('0),                  // No error handling
      .eh_req_valid_i(1'b1),
      .eh_req_ready_o(/*NOT CONNECTED*/),

      .axi_read_req_o(int_axi_read_req[i]),
      .axi_read_rsp_i(int_axi_read_resp[i]),

      .axi_write_req_o(int_axi_write_req[i]),
      .axi_write_rsp_i(int_axi_write_resp[i]),

      .busy_o        (be_busy[i])
    );

    // combine read/write channels into one channel
    axi_mux #(
      .SlvAxiIDWidth(BACKEND_INT_ID_WIDTH),
      .slv_aw_chan_t(int_axi_aw_chan_t),
      .mst_aw_chan_t(mst_axi_aw_chan_t),
      .w_chan_t(mst_axi_w_chan_t), // both int and mst are the same
      .slv_b_chan_t(int_axi_b_chan_t),
      .mst_b_chan_t(mst_axi_b_chan_t),
      .slv_ar_chan_t(int_axi_ar_chan_t),
      .mst_ar_chan_t(mst_axi_ar_chan_t),
      .slv_r_chan_t(int_axi_r_chan_t),
      .mst_r_chan_t(mst_axi_r_chan_t),
      .slv_req_t(int_axi_req_t),
      .slv_resp_t(int_axi_resp_t),
      .mst_req_t(mst_axi_req_t),
      .mst_resp_t(mst_axi_resp_t),
      .NoSlvPorts(2),
      .MaxWTrans(DMA_MST_MAX_TXNS),
      .FallThrough(1'b0),
      .SpillAw(1'b0), // already have cut stage after
      .SpillW(1'b0),
      .SpillB(1'b0),
      .SpillAr(1'b0),
      .SpillR(1'b0)
    ) u_backend_axi_mux (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .test_i(test_en_i),
      .slv_reqs_i({int_axi_read_req[i], int_axi_write_req[i]}),
      .slv_resps_o({int_axi_read_resp[i], int_axi_write_resp[i]}),
      .mst_req_o(mst_axi_req[i]),
      .mst_resp_i(mst_axi_resp[i])
    );

    // add spill register to all axi interface (helps with timing)
    // setting bypass will remove registers
    axi_cut #(
      .Bypass    (BYPASS_DMA_MST_FLOPS),
      .aw_chan_t (mst_axi_aw_chan_t),
      .w_chan_t  (mst_axi_w_chan_t),
      .b_chan_t  (mst_axi_b_chan_t),
      .ar_chan_t (mst_axi_ar_chan_t),
      .r_chan_t  (mst_axi_r_chan_t),
      .axi_req_t (mst_axi_req_t),
      .axi_resp_t(mst_axi_resp_t)
    ) u_dma_out_axi_cut (
      .clk_i     (clk_i),
      .rst_ni    (rst_ni),
      .slv_req_i (mst_axi_req[i]),
      .slv_resp_o(mst_axi_resp[i]),
      .mst_req_o (dma_mst_axi_req_o[i]),
      .mst_resp_i(dma_mst_axi_resp_i[i])
    );
  end

  // be_busy drops once the last W beat is sent, before its B returns; the snoop holds busy
  // until every AW has its B and every AR its last R.
  logic [NUM_MST_INTERFACES-1:0] mst_axi_active;

  for (genvar i = 0; i < NUM_MST_INTERFACES; i++) begin : gen_mst_axi_snoop
    prim_axi_snoop #(
      .OUTSTANDING_TX(2 * DMA_MST_MAX_TXNS)
    ) u_mst_axi_snoop (
      .clk_i           (clk_i),
      .rst_ni          (rst_ni),

      .snoop_aw_valid_i(mst_axi_req[i].aw_valid),
      .snoop_aw_ready_i(mst_axi_resp[i].aw_ready),
      .snoop_w_valid_i (mst_axi_req[i].w_valid),
      .snoop_b_valid_i (mst_axi_resp[i].b_valid),
      .snoop_b_ready_i (mst_axi_req[i].b_ready),
      .snoop_ar_valid_i(mst_axi_req[i].ar_valid),
      .snoop_ar_ready_i(mst_axi_resp[i].ar_ready),
      .snoop_r_valid_i (mst_axi_resp[i].r_valid),
      .snoop_r_ready_i (mst_axi_req[i].r_ready),
      .snoop_r_last_i  (mst_axi_resp[i].r.last),

      .bus_active_o    (mst_axi_active[i]),
      .complete_aw_o   (/* UNUSED */),
      .complete_ar_o   (/* UNUSED */),
      .req_count_q_o   (/* UNUSED */)
    );
  end

  assign dma_backend_busy_o = (|req_valid_i) | (|be_busy) | (|mst_axi_active);

endmodule
