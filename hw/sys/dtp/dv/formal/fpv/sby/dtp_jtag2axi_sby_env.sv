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
  input logic       tck_i,
  input logic       trst_ni,
  input logic       aclk_i,
  input logic       arst_ni,
  input logic       capture_en_i,
  input logic       shift_en_i,
  input logic       update_en_i,
  input logic       select_AXISingleOp_i,
  input logic       select_AXISeriesCtrl_i,
  input logic       select_AXISeriesDataIncr_i,
  input logic       select_AXISeriesDataNoIncr_i,
  input logic       select_AXISeriesDataWithErrorStatus_i,
  input logic       security_disable_i,
  input logic       awvalid_o,
  input logic       awready_i,
  input logic       wvalid_o,
  input logic       wready_i,
  input logic       bvalid_i,
  input logic       bready_o,
  input logic [1:0] bresp_i,
  input logic       arvalid_o,
  input logic       arready_i,
  input logic       rvalid_i,
  input logic       rready_o,
  input logic [1:0] rresp_i,
  input logic       rlast_i,
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
  always_ff @(posedge tck_i) released_q <= 1'b1;

  always_comb begin
    asm_env_resets_asserted : assume (released_q || !(trst_ni || arst_ni));
    asm_env_resets_released : assume (!released_q || (trst_ni && arst_ni));
  end

  // A DR scan opens with Capture-DR and closes with Update-DR.
  logic scan_open_q;
  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) scan_open_q <= 1'b0;
    else if (capture_en_i) scan_open_q <= 1'b1;
    else if (update_en_i) scan_open_q <= 1'b0;
  end

  // In the DTP the disable and the update enable are tck posedge flops, so the value a negedge
  // latch samples is the value the following posedge samples. The free inputs take that shape
  // through a negedge latch and a posedge-sampled assumption.
  logic disable_at_negedge_q, update_at_negedge_q;
  always_ff @(negedge tck_i) begin
    disable_at_negedge_q <= security_disable_i;
    update_at_negedge_q  <= update_en_i;
  end

  // Requests the AXI side accepted and holds no response for.
  logic [2:0] writes_outstanding_q, reads_outstanding_q;
  always_ff @(posedge aclk_i or negedge arst_ni) begin
    if (!arst_ni) begin
      writes_outstanding_q <= '0;
      reads_outstanding_q  <= '0;
    end else begin
      writes_outstanding_q <= writes_outstanding_q + 3'((awvalid_o && awready_i)) -
                              3'((bvalid_i && bready_o));
      reads_outstanding_q  <= reads_outstanding_q + 3'((arvalid_o && arready_i)) -
                              3'((rvalid_i && rready_o && rlast_i));
    end
  end

  // verilog_format: off
  // The TAP raises at most one of capture, shift and update per tck cycle.
  `OCAH_FV_ASSUME(asm_j2a_scan_ctrl_exclusive,
                  $countones({capture_en_i, shift_en_i, update_en_i}) <= 1, tck_i, trst_ni)
  // Update-DR lasts one cycle and closes a scan that Capture-DR opened.
  `OCAH_FV_ASSUME(asm_j2a_update_follows_shift_or_capture,
                  `OCAH_FV_IMPLIES(update_en_i, scan_open_q && !$past(update_en_i)) &&
                  `OCAH_FV_IMPLIES(shift_en_i, scan_open_q),
                  tck_i, trst_ni)
  // The instruction decode raises at most one bridge select.
  `OCAH_FV_ASSUME(asm_j2a_select_one_hot,
                  $countones({select_AXISingleOp_i, select_AXISeriesCtrl_i,
                              select_AXISeriesDataIncr_i, select_AXISeriesDataNoIncr_i,
                              select_AXISeriesDataWithErrorStatus_i}) <= 1,
                  tck_i, trst_ni)
  `OCAH_FV_ASSUME(asm_j2a_controls_tck_synchronous,
                  security_disable_i == disable_at_negedge_q && update_en_i == update_at_negedge_q,
                  tck_i, trst_ni)
  // A response beat arrives only while a request of its kind is outstanding.
  `OCAH_FV_ASSUME(asm_j2a_resp_only_when_outstanding,
                  `OCAH_FV_IMPLIES(bvalid_i, writes_outstanding_q != '0 ||
                                             (awvalid_o && awready_i)) &&
                  `OCAH_FV_IMPLIES(rvalid_i, reads_outstanding_q != '0 ||
                                             (arvalid_o && arready_i)),
                  aclk_i, arst_ni)
  // A valid holds with its payload until its ready.
  `OCAH_FV_ASSUME(asm_j2a_ready_valid_stable,
                  `OCAH_FV_IMPLIES($past(arst_ni) && $past(bvalid_i && !bready_o),
                                   bvalid_i && bresp_i == $past(bresp_i)) &&
                  `OCAH_FV_IMPLIES($past(arst_ni) && $past(rvalid_i && !rready_o),
                                   rvalid_i && rresp_i == $past(rresp_i) &&
                                   rlast_i == $past(rlast_i)),
                  aclk_i, arst_ni)
  // Every request is a single beat, so every read returns one.
  `OCAH_FV_ASSUME(asm_j2a_r_single_beat, `OCAH_FV_IMPLIES(rvalid_i, rlast_i), aclk_i, arst_ni)
  // The machine issues one request and waits for its response, so the crossing delivers a B beat
  // only in WAIT_BRESP and an R beat only in WAIT_RDATA.
  `OCAH_FV_ASSUME(asm_j2a_src_resp_only_when_waiting,
                  `OCAH_FV_IMPLIES(src_b_valid_i, state_i == WAIT_BRESP) &&
                  `OCAH_FV_IMPLIES(src_r_valid_i, state_i == WAIT_RDATA),
                  tck_i, trst_ni)
  `OCAH_FV_ASSUME(asm_j2a_src_ready_valid_stable,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(src_b_valid_i && !src_b_ready_i),
                                   src_b_valid_i && src_b_resp_i == $past(src_b_resp_i)) &&
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(src_r_valid_i && !src_r_ready_i),
                                   src_r_valid_i && src_r_resp_i == $past(src_r_resp_i) &&
                                   src_r_last_i == $past(src_r_last_i)),
                  tck_i, trst_ni)
  `OCAH_FV_ASSUME(asm_j2a_src_r_single_beat, `OCAH_FV_IMPLIES(src_r_valid_i, src_r_last_i),
                  tck_i, trst_ni)
  // verilog_format: on
`endif

endmodule : dtp_jtag2axi_sby_env

bind jtag2axi dtp_jtag2axi_sby_env u_dtp_jtag2axi_sby_env (
  .tck_i                                 (tck_i),
  .trst_ni                               (trst_ni),
  .aclk_i                                (aclk_i),
  .arst_ni                               (arst_ni),
  .capture_en_i                          (capture_en_i),
  .shift_en_i                            (shift_en_i),
  .update_en_i                           (update_en_i),
  .select_AXISingleOp_i                  (select_AXISingleOp_i),
  .select_AXISeriesCtrl_i                (select_AXISeriesCtrl_i),
  .select_AXISeriesDataIncr_i            (select_AXISeriesDataIncr_i),
  .select_AXISeriesDataNoIncr_i          (select_AXISeriesDataNoIncr_i),
  .select_AXISeriesDataWithErrorStatus_i (select_AXISeriesDataWithErrorStatus_i),
  .security_disable_i                    (security_disable_i),
  .awvalid_o                             (awvalid_o),
  .awready_i                             (awready_i),
  .wvalid_o                              (wvalid_o),
  .wready_i                              (wready_i),
  .bvalid_i                              (bvalid_i),
  .bready_o                              (bready_o),
  .bresp_i                               (bresp_i),
  .arvalid_o                             (arvalid_o),
  .arready_i                             (arready_i),
  .rvalid_i                              (rvalid_i),
  .rready_o                              (rready_o),
  .rresp_i                               (rresp_i),
  .rlast_i                               (rlast_i),
  .state_i                               (axi_state_q_tclk),
  .src_b_valid_i                         (src_resp.b_valid),
  .src_b_ready_i                         (src_req.b_ready),
  .src_b_resp_i                          (src_resp.b.resp),
  .src_r_valid_i                         (src_resp.r_valid),
  .src_r_ready_i                         (src_req.r_ready),
  .src_r_resp_i                          (src_resp.r.resp),
  .src_r_last_i                          (src_resp.r.last)
);
