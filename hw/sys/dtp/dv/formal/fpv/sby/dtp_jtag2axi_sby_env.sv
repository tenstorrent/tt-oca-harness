// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment for the jtag2axi formal top: the reset model, the shape of the free
// JTAG-side controls, and the AXI responder's handshake rules. Bound to jtag2axi by the statement
// at the end of this file and read only by the task file.
//
// Both clocks are modelled explicitly, so the asynchronous resets are asserted up to the first tck
// posedge and released there for the rest of the trace. The JTAG-side controls are free inputs
// constrained to the TAP's shape: capture, shift and update never overlap, an update is one cycle
// long and follows a capture, and at most one scan-chain select is high. The bridge's negedge
// update latches sample the disable and the update enable, which in the DTP are tck-synchronous
// flops; a negedge latch and a posedge-sampled assumption give the free inputs that shape. The
// responder rules are the booleans the shared AXI checker states as assertions: a response beat
// arrives only with a request outstanding, a valid holds with its payload until its ready, and a
// read returns a single beat. They are stated twice: on the AXI ports for the ACLK side, and on
// the CDC's response side toward the request machine, which the task file cuts so that the
// machine sees a free responder instead of the CDC round trip and its post-reset clear handshake.

`include "ocah_fv_macros.svh"

module dtp_jtag2axi_sby_env (
  input logic       i_tck,
  input logic       i_trstn,
  input logic       i_aclk,
  input logic       i_arstn,
  input logic       i_capture_en,
  input logic       i_shift_en,
  input logic       i_update_en,
  input logic       i_select_AXISingleOp,
  input logic       i_select_AXISeriesCtrl,
  input logic       i_select_AXISeriesDataIncr,
  input logic       i_select_AXISeriesDataNoIncr,
  input logic       i_select_AXISeriesDataWithErrorStatus,
  input logic       security_disable_i,
  input logic       o_awvalid,
  input logic       i_awready,
  input logic       o_wvalid,
  input logic       i_wready,
  input logic       i_bvalid,
  input logic       o_bready,
  input logic [1:0] i_bresp,
  input logic       o_arvalid,
  input logic       i_arready,
  input logic       i_rvalid,
  input logic       o_rready,
  input logic [1:0] i_rresp,
  input logic       i_rlast,
  // The CDC's response side toward the request machine, a cutpoint in the task file
  input logic [2:0] state_i,         // axi_state_q_tclk
  input logic       src_b_valid_i,   // src_resp.b_valid
  input logic       src_b_ready_i,   // src_req.b_ready
  input logic [1:0] src_b_resp_i,    // src_resp.b.resp
  input logic       src_r_valid_i,   // src_resp.r_valid
  input logic       src_r_ready_i,   // src_req.r_ready
  input logic [1:0] src_r_resp_i,    // src_resp.r.resp
  input logic       src_r_last_i     // src_resp.r.last
);

  // axi_state_e encodings of the states in which the machine waits for a response.
  localparam logic [2:0] WAIT_BRESP = 3'd3;
  localparam logic [2:0] WAIT_RDATA = 3'd5;

`ifdef FORMAL
  logic released_q = 1'b0;
  always_ff @(posedge i_tck) released_q <= 1'b1;

  always_comb begin
    asm_env_resets_asserted : assume (released_q || !(i_trstn || i_arstn));
    asm_env_resets_released : assume (!released_q || (i_trstn && i_arstn));
  end

  // A DR scan opens with Capture-DR and closes with Update-DR.
  logic scan_open_q;
  always_ff @(posedge i_tck or negedge i_trstn) begin
    if (!i_trstn) scan_open_q <= 1'b0;
    else if (i_capture_en) scan_open_q <= 1'b1;
    else if (i_update_en) scan_open_q <= 1'b0;
  end

  // In the DTP the disable and the update enable are tck posedge flops, so the value a negedge
  // latch samples is the value the following posedge samples. The free inputs take that shape
  // through a negedge latch and a posedge-sampled assumption.
  logic disable_at_negedge_q, update_at_negedge_q;
  always_ff @(negedge i_tck) begin
    disable_at_negedge_q <= security_disable_i;
    update_at_negedge_q  <= i_update_en;
  end

  // Requests the AXI side accepted and holds no response for.
  logic [2:0] writes_outstanding_q, reads_outstanding_q;
  always_ff @(posedge i_aclk or negedge i_arstn) begin
    if (!i_arstn) begin
      writes_outstanding_q <= '0;
      reads_outstanding_q  <= '0;
    end else begin
      writes_outstanding_q <= writes_outstanding_q + 3'((o_awvalid && i_awready)) -
                              3'((i_bvalid && o_bready));
      reads_outstanding_q  <= reads_outstanding_q + 3'((o_arvalid && i_arready)) -
                              3'((i_rvalid && o_rready && i_rlast));
    end
  end

  // verilog_format: off
  // The TAP raises at most one of capture, shift and update per tck cycle.
  `OCAH_FV_ASSUME(asm_j2a_scan_ctrl_exclusive,
                  $countones({i_capture_en, i_shift_en, i_update_en}) <= 1, i_tck, i_trstn)
  // Update-DR lasts one cycle and closes a scan that Capture-DR opened.
  `OCAH_FV_ASSUME(asm_j2a_update_follows_shift_or_capture,
                  `OCAH_FV_IMPLIES(i_update_en, scan_open_q && !$past(i_update_en)) &&
                  `OCAH_FV_IMPLIES(i_shift_en, scan_open_q),
                  i_tck, i_trstn)
  // The instruction decode raises at most one bridge select.
  `OCAH_FV_ASSUME(asm_j2a_select_one_hot,
                  $countones({i_select_AXISingleOp, i_select_AXISeriesCtrl,
                              i_select_AXISeriesDataIncr, i_select_AXISeriesDataNoIncr,
                              i_select_AXISeriesDataWithErrorStatus}) <= 1,
                  i_tck, i_trstn)
  `OCAH_FV_ASSUME(asm_j2a_controls_tck_synchronous,
                  security_disable_i == disable_at_negedge_q && i_update_en == update_at_negedge_q,
                  i_tck, i_trstn)
  // A response beat arrives only while a request of its kind is outstanding.
  `OCAH_FV_ASSUME(asm_j2a_resp_only_when_outstanding,
                  `OCAH_FV_IMPLIES(i_bvalid, writes_outstanding_q != '0 ||
                                             (o_awvalid && i_awready)) &&
                  `OCAH_FV_IMPLIES(i_rvalid, reads_outstanding_q != '0 ||
                                             (o_arvalid && i_arready)),
                  i_aclk, i_arstn)
  // A valid holds with its payload until its ready.
  `OCAH_FV_ASSUME(asm_j2a_ready_valid_stable,
                  `OCAH_FV_IMPLIES($past(i_arstn) && $past(i_bvalid && !o_bready),
                                   i_bvalid && i_bresp == $past(i_bresp)) &&
                  `OCAH_FV_IMPLIES($past(i_arstn) && $past(i_rvalid && !o_rready),
                                   i_rvalid && i_rresp == $past(i_rresp) &&
                                   i_rlast == $past(i_rlast)),
                  i_aclk, i_arstn)
  // Every request is a single beat, so every read returns one.
  `OCAH_FV_ASSUME(asm_j2a_r_single_beat, `OCAH_FV_IMPLIES(i_rvalid, i_rlast), i_aclk, i_arstn)
  // The machine issues one request and waits for its response, so the crossing delivers a B beat
  // only in WAIT_BRESP and an R beat only in WAIT_RDATA.
  `OCAH_FV_ASSUME(asm_j2a_src_resp_only_when_waiting,
                  `OCAH_FV_IMPLIES(src_b_valid_i, state_i == WAIT_BRESP) &&
                  `OCAH_FV_IMPLIES(src_r_valid_i, state_i == WAIT_RDATA),
                  i_tck, i_trstn)
  `OCAH_FV_ASSUME(asm_j2a_src_ready_valid_stable,
                  `OCAH_FV_IMPLIES($past(i_trstn) && $past(src_b_valid_i && !src_b_ready_i),
                                   src_b_valid_i && src_b_resp_i == $past(src_b_resp_i)) &&
                  `OCAH_FV_IMPLIES($past(i_trstn) && $past(src_r_valid_i && !src_r_ready_i),
                                   src_r_valid_i && src_r_resp_i == $past(src_r_resp_i) &&
                                   src_r_last_i == $past(src_r_last_i)),
                  i_tck, i_trstn)
  `OCAH_FV_ASSUME(asm_j2a_src_r_single_beat, `OCAH_FV_IMPLIES(src_r_valid_i, src_r_last_i),
                  i_tck, i_trstn)
  // verilog_format: on
`endif

endmodule : dtp_jtag2axi_sby_env

bind jtag2axi dtp_jtag2axi_sby_env u_dtp_jtag2axi_sby_env (
  .i_tck                                 (i_tck),
  .i_trstn                               (i_trstn),
  .i_aclk                                (i_aclk),
  .i_arstn                               (i_arstn),
  .i_capture_en                          (i_capture_en),
  .i_shift_en                            (i_shift_en),
  .i_update_en                           (i_update_en),
  .i_select_AXISingleOp                  (i_select_AXISingleOp),
  .i_select_AXISeriesCtrl                (i_select_AXISeriesCtrl),
  .i_select_AXISeriesDataIncr            (i_select_AXISeriesDataIncr),
  .i_select_AXISeriesDataNoIncr          (i_select_AXISeriesDataNoIncr),
  .i_select_AXISeriesDataWithErrorStatus (i_select_AXISeriesDataWithErrorStatus),
  .security_disable_i                    (security_disable_i),
  .o_awvalid                             (o_awvalid),
  .i_awready                             (i_awready),
  .o_wvalid                              (o_wvalid),
  .i_wready                              (i_wready),
  .i_bvalid                              (i_bvalid),
  .o_bready                              (o_bready),
  .i_bresp                               (i_bresp),
  .o_arvalid                             (o_arvalid),
  .i_arready                             (i_arready),
  .i_rvalid                              (i_rvalid),
  .o_rready                              (o_rready),
  .i_rresp                               (i_rresp),
  .i_rlast                               (i_rlast),
  .state_i                               (axi_state_q_tclk),
  .src_b_valid_i                         (src_resp.b_valid),
  .src_b_ready_i                         (src_req.b_ready),
  .src_b_resp_i                          (src_resp.b.resp),
  .src_r_valid_i                         (src_resp.r_valid),
  .src_r_ready_i                         (src_req.r_ready),
  .src_r_resp_i                          (src_resp.r.resp),
  .src_r_last_i                          (src_resp.r.last)
);
