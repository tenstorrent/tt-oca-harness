// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Assemble the iDMA frontend, request manager, backend, and optional clock gating.
//
// Each control port feeds a register frontend and a 2D midend. The request manager
// distributes the resulting linear requests round-robin across the backends, one per master
// port. The frontend clock is gated by an AXI snoop of control port 0 only, so traffic on
// another control port does not wake it. The request manager and the backends share a second
// gated clock that runs while the frontend or a backend is busy.
//
// Parameter constraints:
//
// - NUM_CTRL_INTERFACES and NUM_MST_INTERFACES must be >= 1.
// - NUM_CTRL_STREAMS must be between 1 and 16.
// - CTRL_OUTSTANDING_TX covers all in-flight transactions the ctrl port admits for the
//   frontend clock-gate snoop and must cover what the upstream fabric can present on
//   dma_ctrl_axi_req_i[0].
// - F2M_FIFO_DEPTH has a minimum depth of 1; otherwise the dma ctrl read bus stalls on
//   command start.
// - BUFFER_DEPTH is the realignment buffer depth in beats and must be >= 2.
// - MST_ID_WIDTH must equal BACKEND_INT_ID_WIDTH + 1.
// - AXI_DATA_WIDTH must be >= 32, the width of the DMA register interface.
// - EN_R_AW_COUPLING is recommended.

module idma_wrapper #(
  parameter  int unsigned NUM_CTRL_INTERFACES = 1,          // Number of AXI4 control ports, each
                                                            // with its own register frontend and 2D
                                                            // midend; must be >= 1.
  parameter  int unsigned NUM_CTRL_STREAMS = 1,             // Streams per control port, from 1 to
                                                            // 16. The register file always has 16
                                                            // stream banks; reading NEXT_ID of a
                                                            // bank at or above this count starts no
                                                            // transfer.

  parameter  int unsigned NUM_MST_INTERFACES = 1,           // Number of AXI4 master ports, each
                                                            // with its own iDMA backend; must be >=
                                                            // 1.

  parameter  int unsigned DMA_MST_MAX_TXNS = 16,            // Maximum AXI transactions each backend
                                                            // keeps in flight on its master port.

  parameter  int unsigned CTRL_OUTSTANDING_TX = 16,         // Outstanding-transaction capacity of
                                                            // the frontend clock-gate snoop on
                                                            // control port 0. Must cover what the
                                                            // upstream fabric can present on
                                                            // dma_ctrl_axi_req_i[0].

  parameter  int unsigned F2M_FIFO_DEPTH = 4,               // Depth of the command FIFO between
                                                            // each register frontend and its 2D
                                                            // midend. Minimum depth of 1; otherwise
                                                            // the dma ctrl read bus stalls on
                                                            // command start.
  parameter  int unsigned M2B_FIFO_DEPTH = 0,               // Depth of the request FIFO between the
                                                            // request manager and each backend; 0
                                                            // connects them directly.
  parameter  int unsigned BUFFER_DEPTH = 3,                 // Depth in beats of each backend's
                                                            // realignment buffer; must be >= 2.

  parameter  bit EN_R_AW_COUPLING = 1,                      // Instantiates the backend R-AW
                                                            // coupling logic, which can hold a
                                                            // write address until its read data
                                                            // arrives; recommended.

  parameter  bit BYPASS_DMA_CTRL_FLOPS = 1'b0,              // Removes the register slice on each
                                                            // control port.
  parameter  bit BYPASS_DMA_MST_FLOPS  = 1'b0,              // Removes the register slice on each
                                                            // master port.

  parameter  int unsigned CG_HYSTERESIS_W = 6,              // Width of cg_hysteresis_i, which
                                                            // bounds the idle wait of both clock
                                                            // gates to 2**CG_HYSTERESIS_W - 1
                                                            // cycles.

  parameter type dma_ctrl_req_t  = logic,                   // AXI4 request type of the control
                                                            // ports; its AW address width sets the
                                                            // DMA register address width.
  parameter type dma_ctrl_resp_t = logic,                   // AXI4 response type of the control
                                                            // ports.

  parameter type dma_mst_req_t  = logic,                    // AXI4 request type of the master
                                                            // ports.
  parameter type dma_mst_resp_t = logic,                    // AXI4 response type of the master
                                                            // ports.

  parameter int unsigned AXI_ADDR_WIDTH       = 56,         // Address width of the master ports,
                                                            // and the width of the transfer
                                                            // addresses, lengths and strides.
  parameter int unsigned AXI_DATA_WIDTH       = 64,         // Data width of both the control AXI
                                                            // port and the AXI master port; must be
                                                            // >= 32.
  parameter int unsigned AXI_USER_WIDTH       = 12,         // User-signal width of both the control
                                                            // AXI port and the AXI master port.
  parameter int unsigned CTRL_ID_WIDTH        = 8,          // ID width of the control ports; must
                                                            // match the ID field of dma_ctrl_req_t.
  parameter int unsigned MST_ID_WIDTH         = 3,          // ID width of the master ports; must
                                                            // match the ID field of dma_mst_req_t
                                                            // and equal BACKEND_INT_ID_WIDTH + 1.
  parameter int unsigned BACKEND_INT_ID_WIDTH = 2           // ID width of the separate read and
                                                            // write managers inside each backend;
                                                            // the backend mux adds one bit to form
                                                            // the master-port ID.
) (
  input  logic clk_i,                                       // Clock; the frontend, request manager
                                                            // and backends run on gated copies of
                                                            // it.
  input  logic rst_ni,                                      // Active-low reset. The iDMA submodules
                                                            // reset asynchronously and the clock
                                                            // gates and interrupt flop
                                                            // synchronously, so deassert it
                                                            // synchronously to clk_i.

  input  logic test_en_i,                                   // Scan test enable, active-high; forces
                                                            // both clock gates open and is
                                                            // forwarded to every submodule.
  output logic dma_busy_o,                                  // High while a command is queued or in
                                                            // a 2D midend, or a backend has a
                                                            // request pending, a transfer active or
                                                            // an AXI response outstanding.
  output logic dma_intp_o,                                  // Completion interrupt: a registered
                                                            // one-cycle pulse in the cycle after
                                                            // dma_busy_o falls, with no enable or
                                                            // mask.

  input  logic cg_enable_i,                                 // Enables both clock gates when high;
                                                            // while it is low both gated clocks run
                                                            // continuously.
  input  logic [CG_HYSTERESIS_W-1:0] cg_hysteresis_i,       // Idle clk_i cycles each clock gate
                                                            // waits after activity ends before it
                                                            // stops its clock.

  input  dma_ctrl_req_t  [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_req_i, // AXI4 control-port requests; each port is
                                                                       // converted to 32-bit DMA register accesses.
  output dma_ctrl_resp_t [NUM_CTRL_INTERFACES-1:0] dma_ctrl_axi_resp_o, // AXI4 control-port responses.

  output dma_mst_req_t   [NUM_MST_INTERFACES-1:0] dma_mst_axi_req_o, // AXI4 master-port requests carrying the
                                                                     // transfer reads and writes.
  input  dma_mst_resp_t  [NUM_MST_INTERFACES-1:0] dma_mst_axi_resp_i, // AXI4 master-port responses.

  output logic                                     frontend_clk_active_o, // High while the frontend gated clock is
                                                                          // running.
  output logic                                     frontend_bus_active_o // High while control port 0 has an AXI
                                                                         // transaction outstanding.
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
