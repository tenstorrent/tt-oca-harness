// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the IEEE 1149.1 TAP controller inside DTP, attached to jtag_tap_ctrlr by
// dtp_tap_bind.sv and checked with dtp as the formal top. Every property body is a boolean
// expression over current and one-cycle-past values, the subset that the open-source frontend and
// the licensed backends both elaborate (hw/common/dv/docs/formal-property-style.adoc).
//
// The TAP runs on tck with the asynchronous trst_n, which the design combines with the power-on
// reset; capture, shift, test-logic-reset and tdo_oen flags are negedge-clocked, so the task file
// models the clocks explicitly and dtp_sby_env.sv supplies the reset environment.

`include "ocah_fv_macros.svh"

module dtp_tap_props
  import jtag_tap_pkg::*;
(
  input logic       tck_i,
  input logic       trst_ni,
  input logic       tms_i,
  input tap_state_e state_i,             // current_state_o
  input logic       tdo_oen_i,           // tdo_oen_o
  input logic       dr_select_i,         // host_dr_scan_ctrl_o.select
  input logic       dr_update_en_i,      // host_dr_scan_ctrl_o.update_en
  input logic       ir_select_i,         // host_ir_scan_ctrl_o.select
  input logic       ir_update_en_i,      // host_ir_scan_ctrl_o.update_en
  input logic       run_test_idle_i,     // host_dr_scan_ctrl_o.run_test_idle
  // Negedge-clocked scan-control flags
  input logic       dr_capture_en_i,     // host_dr_scan_ctrl_o.capture_en
  input logic       dr_shift_en_i,       // host_dr_scan_ctrl_o.shift_en
  input logic       ir_capture_en_i,     // host_ir_scan_ctrl_o.capture_en
  input logic       ir_shift_en_i,       // host_ir_scan_ctrl_o.shift_en
  input logic       test_logic_reset_i   // host_dr_scan_ctrl_o.test_logic_reset
);

  logic [2:0] tms_high_count_q;
  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      tms_high_count_q <= 3'd0;
    end else if (!tms_i) begin
      tms_high_count_q <= 3'd0;
    end else if (tms_high_count_q != 3'd5) begin
      tms_high_count_q <= tms_high_count_q + 3'd1;
    end
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, trst_ni)

  // ---- State register -----------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_tap_state_one_hot, $countones(state_i) == 1, tck_i, trst_ni)

  // IEEE 1149.1: five consecutive tck cycles with tms high reach Test-Logic-Reset from any state.
  `OCAH_FV_ASSERT(ast_tap_five_tms_high_reach_tlr,
                  `OCAH_FV_IMPLIES(tms_high_count_q == 3'd5, state_i == TEST_LOGIC_RESET),
                  tck_i, trst_ni)

  // ---- Transitions --------------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_tap_tlr_holds_on_tms_high,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(state_i) == TEST_LOGIC_RESET &&
                                   $past(tms_i),
                                   state_i == TEST_LOGIC_RESET),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_tap_tlr_exits_to_rti,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(state_i) == TEST_LOGIC_RESET &&
                                   !$past(tms_i),
                                   state_i == RUN_TEST_IDLE),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_tap_rti_holds_on_tms_low,
                  `OCAH_FV_IMPLIES($past(trst_ni) && $past(state_i) == RUN_TEST_IDLE &&
                                   !$past(tms_i),
                                   state_i == RUN_TEST_IDLE),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_tap_shift_holds_on_tms_low,
                  `OCAH_FV_IMPLIES($past(trst_ni) && !$past(tms_i) &&
                                   $past(state_i) inside {SHIFT_DR, SHIFT_IR},
                                   state_i == $past(state_i)),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_tap_update_dr_only_from_exit,
                  `OCAH_FV_IMPLIES($past(trst_ni) && state_i == UPDATE_DR,
                                   $past(tms_i) && $past(state_i) inside {EXIT1_DR, EXIT2_DR}),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_tap_update_ir_only_from_exit,
                  `OCAH_FV_IMPLIES($past(trst_ni) && state_i == UPDATE_IR,
                                   $past(tms_i) && $past(state_i) inside {EXIT1_IR, EXIT2_IR}),
                  tck_i, trst_ni)

  // ---- Scan-control outputs -----------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_tap_select_exclusive, dr_select_i != ir_select_i, tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_tap_moore_flags_follow_state,
                  dr_update_en_i == (state_i == UPDATE_DR) &&
                  ir_update_en_i == (state_i == UPDATE_IR) &&
                  run_test_idle_i == (state_i == RUN_TEST_IDLE),
                  tck_i, trst_ni)
  // Negedge-clocked flags update half a cycle after the state, so at a posedge sample they follow
  // the state sampled at the same edge.
  `OCAH_FV_ASSERT(ast_tap_negedge_flags_follow_state,
                  dr_capture_en_i == (state_i == CAPTURE_DR) &&
                  dr_shift_en_i == (state_i == SHIFT_DR) &&
                  ir_capture_en_i == (state_i == CAPTURE_IR) &&
                  ir_shift_en_i == (state_i == SHIFT_IR) &&
                  test_logic_reset_i == (state_i == TEST_LOGIC_RESET) &&
                  tdo_oen_i == (state_i inside {SHIFT_DR, SHIFT_IR}),
                  tck_i, trst_ni)

  // ---- Covers: one per non-trivial antecedent and per scan path -----------------------------
  `OCAH_FV_COVER(cov_tap_shift_dr, state_i == SHIFT_DR, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_tap_shift_ir, state_i == SHIFT_IR, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_tap_update_dr_from_exit2,
                 state_i == UPDATE_DR && $past(state_i) == EXIT2_DR, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_tap_update_ir_from_exit1,
                 state_i == UPDATE_IR && $past(state_i) == EXIT1_IR, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_tap_tlr_from_five_tms_high,
                 tms_high_count_q == 3'd5 && $past(tms_high_count_q) == 3'd4 &&
                 $past(state_i) != TEST_LOGIC_RESET,
                 tck_i, trst_ni)
  `OCAH_FV_COVER(cov_tap_tdo_driven, tdo_oen_i, tck_i, trst_ni)
  // verilog_format: on

endmodule : dtp_tap_props
