// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Fan a 32-bit AXI-Stream entropy source out to native EDN client ports.
//
// Entropy passes through these pipeline stages in order:
//
// - axis (32b) into a 4-entry prim_fifo_sync staging FIFO.
// - prim_arbiter_ppc round-robin arbitration across N requesters.
// - A per-endpoint 1-deep holding FIFO.
// - edn_ack_sm driving edn_ack / edn_bus.
//
// edn_fips is forwarded from the AXI-Stream tuser sideband through both FIFO stages so a
// FIPS-aware client such as OTBN RND sees correct provenance. Upstream producers drive
// tuser:
//
// - The DRBG native-EDN-to-AXIS adapter forwards edn_fips from u_edn.
// - External streams should drive it from the producer's FIPS policy, commonly tied low
//   when the source is not NIST SP 800-90A approved.
//
// clear_i synchronously flushes staged entropy and every endpoint. endpoint_rst_ni
// cancels only the corresponding endpoint and does not disturb another client's in-flight
// response. Each endpoint reset must assert whenever rst_ni asserts.

module drbg_axis_edn_adapter
  import drbg_pkg::*;
#(
  parameter int unsigned NUM_ENDPOINTS = 4                  // Number of native EDN clients (e.g.
                                                            // AES, KMAC, OTBN RND/URND).
) (
  input  wire logic clk_i,                                  // System clock.
  input  wire logic rst_ni,                                 // Async reset, active-low.
  input  wire logic [NUM_ENDPOINTS-1:0] endpoint_rst_ni,    // Per-client cancel, active-low
                                                            // asynchronous reset of that endpoint.
                                                            // Must assert whenever rst_ni asserts;
                                                            // does not disturb other clients.
  input  wire logic clear_i,                                // Synchronous flush of staged entropy
                                                            // and every endpoint, active-high.

  input  wire drbg_axis_req_t axis_req_i,                   // 32b AXI-Stream sink from the producer
                                                            // (valid/data/strb/tuser). Adapter
                                                            // drives tready; only beats with every
                                                            // tstrb bit set are accepted, and tuser
                                                            // is forwarded as edn_fips.
  output drbg_axis_rsp_t axis_rsp_o,                        // AXI-Stream ready toward the producer;
                                                            // high while the 4-entry staging FIFO
                                                            // has space, all tstrb bits are set and
                                                            // clear_i is low.

  input  wire edn_pkg::edn_req_t [NUM_ENDPOINTS-1:0] edn_req_i, // Native EDN requests from clients.
  output edn_pkg::edn_rsp_t [NUM_ENDPOINTS-1:0] edn_rsp_o   // Native EDN responses to clients; ack,
                                                            // bus and fips are forced to zero
                                                            // during clear_i or that endpoint's
                                                            // reset.
);

  `include "prim_assert.sv"

  localparam int unsigned DataWidth = DRBG_AXIS_DATA_WIDTH;
  localparam int unsigned StageWidth = DataWidth + 1;  // {tuser, tdata}
  localparam int unsigned StageDepth = 4;

  // -------------------------------------------------------------------------
  // Stream staging FIFO (32b data + 1b fips tuser, small depth)
  // -------------------------------------------------------------------------
  logic                           stage_rvalid;
  logic                           stage_rready;
  logic [StageWidth-1:0]          stage_rdata_raw;
  logic [DataWidth-1:0]           stage_rdata;
  logic                           stage_rfips;
  logic                           stage_full;
  logic                           stage_wready;
  logic [$clog2(StageDepth+1)-1:0] unused_stage_depth;
  logic                           unused_stage_err;

  // Accept a stream word only when all strobes are high (32b word) and the
  // staging FIFO has space.
  assign axis_rsp_o.tready = !clear_i && !stage_full && (&axis_req_i.tstrb);

  prim_fifo_sync #(
    .Width             (StageWidth),
    .Pass              (1'b0),
    .Depth             (StageDepth),
    .OutputZeroIfEmpty (1'b1)
  ) u_stage_fifo (
    .clk_i    (clk_i),
    .rst_ni   (rst_ni),
    .clr_i    (clear_i),
    .wvalid_i (axis_req_i.tvalid && axis_rsp_o.tready),
    .wready_o (stage_wready),
    .wdata_i  ({axis_req_i.tuser, axis_req_i.tdata}),
    .rvalid_o (stage_rvalid),
    .rready_i (stage_rready),
    .rdata_o  (stage_rdata_raw),
    .full_o   (stage_full),
    .depth_o  (unused_stage_depth),
    .err_o    (unused_stage_err)
  );

  assign stage_rdata = stage_rdata_raw[DataWidth-1:0];
  assign stage_rfips = stage_rdata_raw[DataWidth];

  logic unused_stage_wready;
  assign unused_stage_wready = stage_wready;

  // -------------------------------------------------------------------------
  // Round-robin arbitration across N endpoint requesters
  // -------------------------------------------------------------------------
  logic [NUM_ENDPOINTS-1:0] arb_req;
  logic [NUM_ENDPOINTS-1:0] arb_gnt;
  logic                     arb_valid;
  logic                     arb_ready;
  logic [0:0]               arb_data_i [NUM_ENDPOINTS];
  logic [0:0]               unused_arb_data_o;

  for (genvar k = 0; k < NUM_ENDPOINTS; k++) begin : gen_arb_data_tie
    assign arb_data_i[k] = 1'b0;
  end

  prim_arbiter_ppc #(
    .N          (NUM_ENDPOINTS),
    .DW         (1),
    .EnDataPort (1'b0)
  ) u_arbiter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .req_chk_i (!clear_i && (&endpoint_rst_ni)),
    .req_i     (arb_req),
    .data_i    (arb_data_i),
    .gnt_o     (arb_gnt),
    .idx_o     (),
    .valid_o   (arb_valid),
    .data_o    (unused_arb_data_o),
    .ready_i   (arb_ready)
  );

  // Only honour a grant when the staging FIFO actually has a word.
  assign arb_ready    = stage_rvalid;
  assign stage_rready = arb_valid && stage_rvalid;

  // -------------------------------------------------------------------------
  // Per-endpoint 1-deep holding FIFO + edn_ack_sm
  // -------------------------------------------------------------------------
  logic [NUM_ENDPOINTS-1:0] ep_clr;
  logic [NUM_ENDPOINTS-1:0] ep_push;
  logic [NUM_ENDPOINTS-1:0] ep_wready;
  logic [NUM_ENDPOINTS-1:0] ep_rvalid;
  logic [StageWidth-1:0]    ep_rdata_raw [NUM_ENDPOINTS];
  logic [NUM_ENDPOINTS-1:0] ep_pop;
  logic [NUM_ENDPOINTS-1:0] ep_ack;
  logic [NUM_ENDPOINTS-1:0] ep_err;
  logic [NUM_ENDPOINTS-1:0] ack_sm_err;
  logic [NUM_ENDPOINTS-1:0] endpoint_active;

  for (genvar i = 0; i < NUM_ENDPOINTS; i++) begin : gen_ep
    // Hold arbitration off while edn_ack_sm performs its post-reset FIFO clear.
    always_ff @(posedge clk_i or negedge endpoint_rst_ni[i]) begin
      if (!endpoint_rst_ni[i]) begin
        endpoint_active[i] <= 1'b0;
      end else if (clear_i) begin
        endpoint_active[i] <= 1'b0;
      end else begin
        endpoint_active[i] <= 1'b1;
      end
    end

    // Only request when the client asks and we don't already hold a word.
    assign arb_req[i] = endpoint_active[i] && edn_req_i[i].edn_req && !ep_rvalid[i];

    // Push the staged word into the winning endpoint's holding FIFO.
    assign ep_push[i] = endpoint_active[i] && stage_rready && arb_gnt[i];

    prim_fifo_sync #(
      .Width             (StageWidth),
      .Pass              (1'b0),
      .Depth             (1),
      .OutputZeroIfEmpty (1'b1)
    ) u_ep_fifo (
      .clk_i    (clk_i),
      .rst_ni   (endpoint_rst_ni[i]),
      .clr_i    (ep_clr[i] | clear_i),
      .wvalid_i (ep_push[i]),
      .wready_o (ep_wready[i]),
      .wdata_i  ({stage_rfips, stage_rdata}),
      .rvalid_o (ep_rvalid[i]),
      .rready_i (ep_pop[i]),
      .rdata_o  (ep_rdata_raw[i]),
      .full_o   (),
      .depth_o  (),
      .err_o    (ep_err[i])
    );

    edn_ack_sm u_edn_ack_sm (
      .clk_i            (clk_i),
      .rst_ni           (endpoint_rst_ni[i]),
      .enable_i         (!clear_i && endpoint_rst_ni[i]),
      .req_i            (edn_req_i[i].edn_req),
      .ack_o            (ep_ack[i]),
      .fifo_not_empty_i (ep_rvalid[i]),
      .fifo_pop_o       (ep_pop[i]),
      .fifo_clr_o       (ep_clr[i]),
      .local_escalate_i (1'b0),
      .ack_sm_err_o     (ack_sm_err[i])
    );

    assign edn_rsp_o[i].edn_ack = ep_ack[i] & ~clear_i & endpoint_rst_ni[i];
    assign edn_rsp_o[i].edn_bus =
        (clear_i || !endpoint_rst_ni[i]) ? '0 : ep_rdata_raw[i][DataWidth-1:0];
    // FIPS forwarded per-beat from the AXI-Stream tuser sideband.
    assign edn_rsp_o[i].edn_fips =
        (clear_i || !endpoint_rst_ni[i]) ? 1'b0 : ep_rdata_raw[i][DataWidth];

    `OCAH_OT_ASSERT(AxisEdnNoAckDuringClear_A, clear_i |-> !edn_rsp_o[i].edn_ack)
    `OCAH_OT_ASSERT(AxisEdnReqStableUnlessEndpointReset_A,
                    arb_req[i] && !arb_gnt[i] && endpoint_rst_ni[i] |=>
                    arb_req[i] || !endpoint_rst_ni[i] || clear_i)
  end

  logic unused_ep_wready;
  logic unused_ep_err;
  assign unused_ep_wready = |ep_wready;
  assign unused_ep_err    = |ep_err;

  // -------------------------------------------------------------------------
  // Assertions
  // -------------------------------------------------------------------------
  `OCAH_OT_ASSERT(AxisEdnAllAckSmHealthy_A, !(|ack_sm_err))

  `OCAH_OT_ASSERT(AxisEdnStableDataWhenStall_A,
                  !clear_i && axis_req_i.tvalid && !axis_rsp_o.tready |=> clear_i || $stable
                  (axis_req_i.tdata))
  `OCAH_OT_ASSERT(AxisEdnStableStrbWhenStall_A,
                  !clear_i && axis_req_i.tvalid && !axis_rsp_o.tready |=> clear_i || $stable
                  (axis_req_i.tstrb))
  `OCAH_OT_ASSERT_KNOWN(AxisEdnRspReadyKnown_A, axis_rsp_o.tready)
  `OCAH_OT_ASSERT(AxisEdnNoReadyDuringClear_A, clear_i |-> !axis_rsp_o.tready)

  `OCAH_OT_ASSERT_INIT(AxisEdnEndpointCount_A, NUM_ENDPOINTS > 0)

endmodule : drbg_axis_edn_adapter
