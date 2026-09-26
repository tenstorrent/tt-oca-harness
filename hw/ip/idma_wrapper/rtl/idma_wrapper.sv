// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Assemble the iDMA frontend, request manager, backend, and optional clock gating.
//
// Parameter constraints:
//
// - NUM_CTRL_INTERFACES, NUM_CTRL_STREAMS, and NUM_MST_INTERFACES must be >= 1.
// - CTRL_OUTSTANDING_TX covers all in-flight transactions the ctrl port admits for the
//   frontend clock-gate snoop and must cover what the upstream fabric can present on
//   dma_ctrl_axi_req_i[0].
// - F2M_FIFO_DEPTH has a minimum depth of 1; otherwise the dma ctrl read bus stalls on
//   command start.
// - BUFFER_DEPTH is the realignment buffer depth in beats and must be >= 2.
// - EN_R_AW_COUPLING is recommended.

module idma_wrapper #(
  parameter  int unsigned NUM_CTRL_INTERFACES = 1,          // Control-port count; must be >= 1.
  parameter  int unsigned NUM_CTRL_STREAMS = 1,             // Streams per control port; must be >= 1.

  parameter  int unsigned NUM_MST_INTERFACES = 1,           // Backend master count; must be >= 1.

  parameter  int unsigned DMA_MST_MAX_TXNS = 16,            // Max outstanding AXI master transactions.

  parameter  int unsigned CTRL_OUTSTANDING_TX = 16,         // Ctrl-port outstanding for the frontend clock-gate snoop.
                                                            // Must cover what the upstream fabric can present on dma_ctrl_axi_req_i[0].

  parameter  int unsigned F2M_FIFO_DEPTH = 4,               // Frontend-to-manager FIFO depth.
                                                            // Minimum depth of 1; otherwise the dma ctrl read bus stalls on command start.
  parameter  int unsigned M2B_FIFO_DEPTH = 0,               // Manager-to-backend FIFO depth.
  parameter  int unsigned BUFFER_DEPTH = 3,                 // Realignment buffer depth in beats; must be >= 2.

  parameter  bit EN_R_AW_COUPLING = 1,                      // Couple R and AW channels; recommended.

  parameter  bit BYPASS_DMA_CTRL_FLOPS = 1'b0,              // Skip AXI ctrl boundary flops.
  parameter  bit BYPASS_DMA_MST_FLOPS  = 1'b0,              // Skip AXI master boundary flops.

  parameter  int unsigned CG_HYSTERESIS_W = 6,              // Clock-gater hysteresis width.

  parameter type dma_ctrl_req_t  = logic,                   // AXI ctrl request type.
  parameter type dma_ctrl_resp_t = logic,                   // AXI ctrl response type.

  parameter type dma_mst_req_t  = logic,                    // AXI master request type.
  parameter type dma_mst_resp_t = logic,                    // AXI master response type.

  parameter int unsigned AXI_ADDR_WIDTH       = 56,         // AXI address width.
  parameter int unsigned AXI_DATA_WIDTH       = 64,         // AXI data width.
  parameter int unsigned AXI_USER_WIDTH       = 12,         // AXI user width.
  parameter int unsigned CTRL_ID_WIDTH        = 8,          // Ctrl AXI ID width.
  parameter int unsigned MST_ID_WIDTH         = 3,          // Master AXI ID width.
  parameter int unsigned BACKEND_INT_ID_WIDTH = 2           // Internal backend ID width.
) (
  input  logic clk_i,                                       // System clock.
  input  logic rst_ni,                                      // Async reset, active-low.

  input  logic test_en_i,                                   // DFT test enable.
  output logic dma_busy_o,                                  // DMA has work in flight.
  output logic dma_intp_o,                                  // DMA completion interrupt.

  input  logic cg_enable_i,                                 // Enable frontend clock gating.
  input  logic [CG_HYSTERESIS_W-1:0] cg_hysteresis_i,       // Idle cycles before gating.

  input  dma_ctrl_req_t  [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_req_i, // AXI ctrl slave request.
  output dma_ctrl_resp_t [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_resp_o, // AXI ctrl slave response.

  output dma_mst_req_t   [NUM_MST_INTERFACES-1:0] dma_mst_axi_req_o, // AXI master request.
  input  dma_mst_resp_t  [NUM_MST_INTERFACES-1:0] dma_mst_axi_resp_i, // AXI master response.

  output logic                                     frontend_clk_active_o, // Frontend clock is running.
  output logic                                     frontend_bus_active_o // Frontend bus has traffic.
);

  `include "idma/typedef.svh"

  //////////////////////////////////////////
  // Setup iDMA Internal Typedefs/Structs //
  //////////////////////////////////////////

  // Local type derivations from width parameters
  typedef logic [AXI_ADDR_WIDTH-1:0] axi_addr_t;
  typedef logic [MST_ID_WIDTH-1:0] mst_id_t;

  // Control interface address width derived from ctrl type (9-bit for DMA regs)
  localparam int unsigned CTRL_ADDR_WIDTH = $bits(dma_ctrl_axi_req_i[0].aw.addr);

  localparam int unsigned TFLenWidth = AXI_ADDR_WIDTH;  // width for representing transaction length
  localparam int unsigned NumDim = 2;  // 2 dimensions to support 2d transfers
  localparam int unsigned RepWidth = 32;  // width to represent repetition length
  localparam int unsigned StrideWidth = AXI_ADDR_WIDTH;  // width to represent stride
  typedef logic [TFLenWidth-1:0] tf_len_t;
  typedef logic [RepWidth-1:0] reps_t;
  typedef logic [StrideWidth-1:0] strides_t;

  // iDMA request / response types
  `IDMA_TYPEDEF_FULL_REQ_T(idma_req_t, mst_id_t, axi_addr_t, tf_len_t)
  `IDMA_TYPEDEF_FULL_RSP_T(idma_resp_t, axi_addr_t)

  // iDMA ND request
  `IDMA_TYPEDEF_FULL_ND_REQ_T(idma_nd_req_t, idma_req_t, reps_t, strides_t)

  // frontend to request manager
  idma_req_t [NUM_CTRL_INTERFACES-1:0] f2r_req;
  logic [NUM_CTRL_INTERFACES-1:0] f2r_req_valid, f2r_req_ready;

  idma_resp_t [NUM_CTRL_INTERFACES-1:0] f2r_resp;
  logic [NUM_CTRL_INTERFACES-1:0] f2r_resp_valid, f2r_resp_ready;

  // request manager to backend
  idma_req_t [NUM_MST_INTERFACES-1:0] r2b_req;
  logic [NUM_MST_INTERFACES-1:0] r2b_req_valid, r2b_req_ready;

  idma_resp_t [NUM_MST_INTERFACES-1:0] r2b_resp;
  logic [NUM_MST_INTERFACES-1:0] r2b_resp_valid, r2b_resp_ready;

  /////////////////
  // Clock-gater //
  /////////////////

  logic dma_frontend_busy, dma_frontend_wakeup, dma_backend_busy;
  logic clk_active;
  logic frontend_clock, local_clock;
  logic dma_busy;
  assign dma_busy = dma_frontend_wakeup | dma_backend_busy;

  axi_cg_snoop #(
    // Full AXI4 ctrl port: all IDs, both directions (see CTRL_OUTSTANDING_TX)
    .OutstandingTx(CTRL_OUTSTANDING_TX),
    .DenyDelay(1),
    .HystWidth(CG_HYSTERESIS_W)
  ) u_frontend_cg (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),

    .snoop_aw_valid_i(dma_ctrl_axi_req_i[0].aw_valid),
    .snoop_aw_ready_i(dma_ctrl_axi_resp_o[0].aw_ready),
    .snoop_w_valid_i (dma_ctrl_axi_req_i[0].w_valid),
    .snoop_b_valid_i (dma_ctrl_axi_resp_o[0].b_valid),
    .snoop_b_ready_i (dma_ctrl_axi_req_i[0].b_ready),
    .snoop_ar_valid_i(dma_ctrl_axi_req_i[0].ar_valid),
    .snoop_ar_ready_i(dma_ctrl_axi_resp_o[0].ar_ready),
    .snoop_r_valid_i (dma_ctrl_axi_resp_o[0].r_valid),
    .snoop_r_ready_i (dma_ctrl_axi_req_i[0].r_ready),
    .snoop_r_last_i  (dma_ctrl_axi_resp_o[0].r.last), // every beat is "last" in AXI-L

    .kick_i          (~cg_enable_i | dma_busy), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_hysteresis_i),
    .clk_active_o    (frontend_clk_active_o),
    .gated_clk_o     (frontend_clock),
    .bus_active_o    (frontend_bus_active_o)
  );

  prim_clk_gater_hysteresis #(
    .HYST_WIDTH(CG_HYSTERESIS_W)
  ) u_request_maneger_cg (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .busy_i(dma_busy),      // when dma busy, enable the clock
    .enable_i(1'b1),
    .kick_i(~cg_enable_i),  // when cg is not enable, always kick to always keep the clock on
    .test_clk_en_i(test_en_i),
    .hysteresis_i(cg_hysteresis_i),
    .clk_active_o(clk_active),
    .gated_clk_o(local_clock)
  );

  assign dma_busy_o = dma_frontend_busy | dma_backend_busy;

  // Falling-edge pulse of dma_busy_o (transfer-complete interrupt)
  logic dma_prev_busy;
  always_ff @(posedge clk_i) begin
    if (~rst_ni) begin
      dma_prev_busy <= 1'b0;
      dma_intp_o    <= 1'b0;
    end else begin
      dma_prev_busy <= dma_busy_o;
      dma_intp_o    <= dma_prev_busy & ~dma_busy_o;
    end
  end

  //////////////
  // Frontend //
  //////////////

  idma_frontend_wrapper #(
    .NUM_CTRL_INTERFACES(NUM_CTRL_INTERFACES),
    .NUM_CTRL_STREAMS(NUM_CTRL_STREAMS),
    .F2M_FIFO_DEPTH(F2M_FIFO_DEPTH),
    .BYPASS_DMA_CTRL_FLOPS(BYPASS_DMA_CTRL_FLOPS),
    .NumDim(NumDim),
    .RepWidth(RepWidth),
    .idma_req_t(idma_req_t),
    .idma_resp_t(idma_resp_t),
    .idma_nd_req_t(idma_nd_req_t),
    .dma_mst_addr_t(axi_addr_t),
    .dma_ctrl_req_t(dma_ctrl_req_t),
    .dma_ctrl_resp_t(dma_ctrl_resp_t),
    .CTRL_ADDR_WIDTH(CTRL_ADDR_WIDTH),
    .CTRL_DATA_WIDTH(AXI_DATA_WIDTH),
    .CTRL_ID_WIDTH(CTRL_ID_WIDTH),
    .CTRL_USER_WIDTH(AXI_USER_WIDTH)
  ) u_idma_frontend_wrapper (
    .clk_i(frontend_clock),
    .rst_ni(rst_ni),
    .test_en_i(test_en_i),

    .dma_frontend_wakeup_o(dma_frontend_wakeup),
    .dma_frontend_busy_o(dma_frontend_busy),

    .dma_ctrl_axi_req_i(dma_ctrl_axi_req_i),
    .dma_ctrl_axi_resp_o(dma_ctrl_axi_resp_o),

    .req_o(f2r_req),
    .req_valid_o(f2r_req_valid),
    .req_ready_i(f2r_req_ready),
    .resp_i(f2r_resp),
    .resp_valid_i(f2r_resp_valid),
    .resp_ready_o(f2r_resp_ready)
  );

  /////////////////////
  // Request manager //
  /////////////////////

  // distributes requests from NUM_CTRL_INTERFACES requesters to NUM_MST_INTERFACES workers
  idma_request_manager_wrapper #(
    .NUM_CTRL_INTERFACES(NUM_CTRL_INTERFACES),
    .NUM_MST_INTERFACES(NUM_MST_INTERFACES),
    .req_t(idma_req_t),
    .resp_t(idma_resp_t)
  ) u_idma_request_manager_wrapper (
    .clk_i(local_clock),
    .rst_ni(rst_ni),
    .test_en_i(test_en_i),

    .ctrl_req_i(f2r_req),
    .ctrl_req_valid_i(f2r_req_valid),
    .ctrl_req_ready_o(f2r_req_ready),

    .ctrl_resp_o(f2r_resp),
    .ctrl_resp_valid_o(f2r_resp_valid),
    .ctrl_resp_ready_i(f2r_resp_ready),

    .mst_req_o(r2b_req),
    .mst_req_valid_o(r2b_req_valid),
    .mst_req_ready_i(r2b_req_ready),

    .mst_resp_i(r2b_resp),
    .mst_resp_valid_i(r2b_resp_valid),
    .mst_resp_ready_o(r2b_resp_ready)
  );

  /////////////
  // Backend //
  /////////////

  idma_backend_wrapper #(
    .NUM_MST_INTERFACES(NUM_MST_INTERFACES),
    .DMA_MST_MAX_TXNS(DMA_MST_MAX_TXNS),
    .M2B_FIFO_DEPTH(M2B_FIFO_DEPTH),
    .BUFFER_DEPTH(BUFFER_DEPTH),
    .EN_R_AW_COUPLING(EN_R_AW_COUPLING),
    .BYPASS_DMA_MST_FLOPS(BYPASS_DMA_MST_FLOPS),
    .TFLenWidth(TFLenWidth),
    .idma_req_t(idma_req_t),
    .idma_resp_t(idma_resp_t),
    .dma_mst_req_t(dma_mst_req_t),
    .dma_mst_resp_t(dma_mst_resp_t),
    .AXI_ADDR_WIDTH(AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH(AXI_DATA_WIDTH),
    .AXI_USER_WIDTH(AXI_USER_WIDTH),
    .MST_ID_WIDTH(MST_ID_WIDTH),
    .BACKEND_INT_ID_WIDTH(BACKEND_INT_ID_WIDTH)
  ) u_idma_backend_wrapper (
    .clk_i(local_clock),
    .rst_ni(rst_ni),
    .test_en_i(test_en_i),

    .dma_backend_busy_o(dma_backend_busy),

    .req_i(r2b_req),
    .req_valid_i(r2b_req_valid),
    .req_ready_o(r2b_req_ready),
    .resp_o(r2b_resp),
    .resp_valid_o(r2b_resp_valid),
    .resp_ready_i(r2b_resp_ready),

    .dma_mst_axi_req_o(dma_mst_axi_req_o),
    .dma_mst_axi_resp_i(dma_mst_axi_resp_i)
  );

endmodule
