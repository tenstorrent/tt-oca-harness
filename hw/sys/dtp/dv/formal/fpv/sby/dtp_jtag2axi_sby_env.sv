// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment for the jtag2axi formal top: the reset model, the shape of the free
// JTAG-side controls, and the one fact about the AXI responder that the protocol leaves open.
// Bound to jtag2axi by the statement at the end of this file and read only by the task file.
//
// Both clocks are modelled explicitly, so the asynchronous resets are asserted up to the first tck
// posedge and released there for the rest of the trace. The JTAG-side controls are free inputs
// constrained to the TAP's shape: capture, shift and update never overlap, an update is one cycle
// long and follows a capture, and at most one scan-chain select is high. The bridge's negedge
// update latches sample the disable and the update enable, which in the DTP are tck-synchronous
// flops; a negedge latch and a posedge-sampled assumption give the free inputs that shape. The
// responder's handshake rules are the shared AXI checker's, bound in assume mode by
// dtp_jtag2axi_axi_fv_bind.sv on the CDC's response side toward the request machine, which the
// task file cuts so that the machine sees a free responder instead of the CDC round trip and its
// post-reset clear handshake. Every request the bridge issues is a single
// beat, so every read returns one; this module states that fact on both sides.

`include "ocah_fv_macros.svh"

module dtp_jtag2axi_sby_env (
  input logic tck_i,
  input logic trst_ni,
  input logic aclk_i,
  input logic arst_ni,
  input logic capture_en_i,
  input logic shift_en_i,
  input logic update_en_i,
  input logic select_AXISingleOp_i,
  input logic select_AXISeriesCtrl_i,
  input logic select_AXISeriesDataIncr_i,
  input logic select_AXISeriesDataNoIncr_i,
  input logic select_AXISeriesDataWithErrorStatus_i,
  input logic security_disable_i,
  input logic rvalid_i,
  input logic rlast_i,
  // The CDC's response side toward the request machine, a cutpoint in the task file
  input logic src_r_valid_i,  // src_resp.r_valid
  input logic src_r_last_i    // src_resp.r.last
);

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

  // verilog_format: off
  // The TAP raises at most one of capture, shift and update per tck cycle.
  `OCAH_FV_ASSUME(asm_env_scan_ctrl_exclusive,
                  $countones({capture_en_i, shift_en_i, update_en_i}) <= 1, tck_i, trst_ni)
  // Update-DR lasts one cycle and closes a scan that Capture-DR opened.
  `OCAH_FV_ASSUME(asm_env_update_follows_shift_or_capture,
                  `OCAH_FV_IMPLIES(update_en_i,
                                   scan_open_q && !($past(trst_ni) && $past(update_en_i))) &&
                  `OCAH_FV_IMPLIES(shift_en_i, scan_open_q),
                  tck_i, trst_ni)
  // The instruction decode raises at most one bridge select.
  `OCAH_FV_ASSUME(asm_env_select_one_hot,
                  $countones({select_AXISingleOp_i, select_AXISeriesCtrl_i,
                              select_AXISeriesDataIncr_i, select_AXISeriesDataNoIncr_i,
                              select_AXISeriesDataWithErrorStatus_i}) <= 1,
                  tck_i, trst_ni)
  `OCAH_FV_ASSUME(asm_env_controls_tck_synchronous,
                  security_disable_i == disable_at_negedge_q && update_en_i == update_at_negedge_q,
                  tck_i, trst_ni)
  // Every request is a single beat, so every read returns one, on the AXI ports and on the CDC's
  // response side.
  `OCAH_FV_ASSUME(asm_env_r_single_beat, `OCAH_FV_IMPLIES(rvalid_i, rlast_i), aclk_i, arst_ni)
  `OCAH_FV_ASSUME(asm_env_src_r_single_beat, `OCAH_FV_IMPLIES(src_r_valid_i, src_r_last_i),
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
  .rvalid_i                              (rvalid_i),
  .rlast_i                               (rlast_i),
  .src_r_valid_i                         (src_resp.r_valid),
  .src_r_last_i                          (src_resp.r.last)
);
