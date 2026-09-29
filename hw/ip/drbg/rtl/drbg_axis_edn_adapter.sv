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
// clear_i synchronously flushes staged entropy and every endpoint. endpoint_cancel_i
// synchronously cancels only the corresponding endpoint and does not disturb another client's
// in-flight response. It must assert before the client's reset asserts and hold until that
// reset deasserts.
module drbg_axis_edn_adapter
  import drbg_pkg::*;
#(
  parameter int unsigned NUM_ENDPOINTS = 4                  // Number of native EDN clients (e.g.
                                                            // AES, KMAC, OTBN RND/URND).
) (
  input  wire logic clk_i,                                  // System clock.
  input  wire logic rst_ni,                                 // Async reset, active-low.
  input  wire logic [NUM_ENDPOINTS-1:0] endpoint_cancel_i,  // Per-client synchronous cancel.
                                                            // Must assert before its reset and
                                                            // hold until the reset deasserts;
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
  logic                     arb_req_chk;
  logic [NUM_ENDPOINTS-1:0] ep_flush;
  logic [NUM_ENDPOINTS-1:0] ep_flush_q;
  logic [NUM_ENDPOINTS-1:0] ep_live;
  logic [NUM_ENDPOINTS-1:0] ep_flush_start;
  logic                     arb_valid;
  logic                     arb_ready;
  logic [0:0]               arb_data_i [NUM_ENDPOINTS];
  logic [0:0]               unused_arb_data_o;

  for (genvar k = 0; k < NUM_ENDPOINTS; k++) begin : gen_arb_data_tie
    assign arb_data_i[k] = 1'b0;
  end

  // A flush withdraws an ungranted request on its first cycle. Waive the
  // arbiter's request checks only then, so sibling requests remain checked.
  assign arb_req_chk = !(|ep_flush_start);

  prim_arbiter_ppc #(
    .N          (NUM_ENDPOINTS),
    .DW         (1),
    .EnDataPort (1'b0)
  ) u_arbiter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .req_chk_i (arb_req_chk),
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

  for (genvar i = 0; i < NUM_ENDPOINTS; i++) begin : gen_ep
    // Global clear or this endpoint's cancel flushes the endpoint.
    assign ep_flush[i] = clear_i || endpoint_cancel_i[i];

    // edn_ack_sm clears the holding FIFO on the first cycle after a flush ends,
    // so the endpoint rejoins arbitration a cycle later to keep a granted word
    // from being cleared.
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        ep_flush_q[i] <= 1'b1;
      end else begin
        ep_flush_q[i] <= ep_flush[i];
      end
    end

    // Every use of edn_req_i is gated by ep_live, so a client reset that
    // follows its cancel cannot reach a flop in this rst_ni domain.
    assign ep_live[i]        = !ep_flush[i] && !ep_flush_q[i];
    assign ep_flush_start[i] = ep_flush[i] && !ep_flush_q[i];

    // Only request when the client asks and we don't already hold a word.
    assign arb_req[i] = ep_live[i] && edn_req_i[i].edn_req && !ep_rvalid[i];

    // Push the staged word into the winning endpoint's holding FIFO.
    assign ep_push[i] = ep_live[i] && stage_rready && arb_gnt[i];

    prim_fifo_sync #(
      .Width             (StageWidth),
      .Pass              (1'b0),
      .Depth             (1),
      .OutputZeroIfEmpty (1'b1)
    ) u_ep_fifo (
      .clk_i    (clk_i),
      .rst_ni   (rst_ni),
      .clr_i    (ep_clr[i] | ep_flush[i]),
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
      .rst_ni           (rst_ni),
      .enable_i         (!ep_flush[i]),
      .req_i            (edn_req_i[i].edn_req && ep_live[i]),
      .ack_o            (ep_ack[i]),
      .fifo_not_empty_i (ep_rvalid[i]),
      .fifo_pop_o       (ep_pop[i]),
      .fifo_clr_o       (ep_clr[i]),
      .local_escalate_i (1'b0),
      .ack_sm_err_o     (ack_sm_err[i])
    );

    assign edn_rsp_o[i].edn_ack = ep_ack[i] & ~ep_flush[i];
    assign edn_rsp_o[i].edn_bus = ep_flush[i] ? '0 : ep_rdata_raw[i][DataWidth-1:0];
    // FIPS forwarded per-beat from the AXI-Stream tuser sideband.
    assign edn_rsp_o[i].edn_fips = ep_flush[i] ? 1'b0 : ep_rdata_raw[i][DataWidth];

    `OCAH_OT_ASSERT(AxisEdnNoAckDuringClear_A, clear_i |-> !edn_rsp_o[i].edn_ack)
    `OCAH_OT_ASSERT(AxisEdnCancelledEndpointIdle_A,
                    endpoint_cancel_i[i] |-> !arb_req[i] && !ep_push[i] && !edn_rsp_o[i].edn_ack)
    `OCAH_OT_ASSERT(AxisEdnReqStableUnlessEndpointCancelled_A,
                    arb_req[i] && !arb_gnt[i] |=> arb_req[i] || ep_flush[i])
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
