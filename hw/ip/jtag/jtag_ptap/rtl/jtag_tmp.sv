// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Track IEEE 1149.1 test-mode persistence for clamp hold and release.
//
// Enters and leaves persistence-on from CLAMP_HOLD, CLAMP_RELEASE, and BYPASS instruction
// selects.
// bypass_escape_enable_i from the status TDR allows BYPASS to leave persistence-on.
// update_ir_i marks IR updates; test_logic_reset_i is not used, so the mode persists
// through Test-Logic-Reset and only trst_n returns it to Persistence-Off.
// persistence_mode_o is 1 for Persistence-On and 0 for Persistence-Off.

module jtag_tmp
  import prim_jtag_pkg::*;
  import jtag_tmp_pkg::*;
(
  input  jtag_tap_ctrl_t  tap_ctrl_i,   // JTAG TAP control; tck clocks the state, trst_n resets it,
                                        // and tms is not used.

  input  logic             update_ir_i,  // IR update enable from the TAP, high in Update-IR;
                                         // qualifies the BYPASS escape from persistence-on.

  input  logic             test_logic_reset_i,  // Test-Logic-Reset state from the TAP controller;
                                                // not used.

  input  logic             clamp_hold_selected_i,  // CLAMP_HOLD instruction selected; enters
                                                   // Persistence-On on the next rising TCK.
  input  logic             clamp_release_selected_i,  // CLAMP_RELEASE instruction selected; leaves
                                                      // Persistence-On on the next rising TCK.
  input  logic             bypass_selected_i,  // BYPASS instruction selected; leaves Persistence-On
                                               // in Update-IR when bypass_escape_enable_i is set.

  output logic             persistence_mode_o,  // 1 = Persistence-On, 0 = Persistence-Off.

  input  logic             bypass_escape_enable_i  // Bypass escape enable from the status register;
                                                   // lets BYPASS leave Persistence-On.
);
  // Tie off unused fields to satisfy lint
  logic unused_tap;
  assign unused_tap = ^{test_logic_reset_i, tap_ctrl_i.tms};

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  // TMP controller state machine
  tmp_state_e tmp_state_q, tmp_state_d;
  logic [$bits(tmp_state_e)-1:0] tmp_state_q_bits;

  assign tmp_state_q = tmp_state_e'(tmp_state_q_bits);

  // Internal control signals
  logic bypass_escape_condition;
  logic clamp_hold_trigger;
  logic clamp_release_trigger;

  //--------------------------------------------------------------------------
  // State Machine Control Logic
  //--------------------------------------------------------------------------

  // CLAMP_HOLD triggers on any rising edge of TCK when instruction is active
  assign clamp_hold_trigger = clamp_hold_selected_i;

  // CLAMP_RELEASE triggers on any rising edge of TCK when instruction is active
  assign clamp_release_trigger = clamp_release_selected_i;

  // BYPASS-Escape condition per IEEE 1149.1 Section 6.2.1.1
  // Occurs when:
  // - TAP controller is in Update-IR state
  // - Explicit BYPASS instruction is active (not undefined instructions)
  // - bypass_escape_enable_i is set (1) - comes from the TMP status register
  assign bypass_escape_condition = update_ir_i & bypass_selected_i & bypass_escape_enable_i;

  //--------------------------------------------------------------------------
  // TMP Controller State Machine
  //--------------------------------------------------------------------------

  // Next state logic
  always_comb begin
    tmp_state_d = tmp_state_q;  // Default: hold current state

    case (tmp_state_q)
      TMP_PERSISTENCE_OFF: begin
        if (clamp_hold_trigger) begin
          tmp_state_d = TMP_PERSISTENCE_ON;
        end
      end

      TMP_PERSISTENCE_ON: begin
        if (clamp_release_trigger || bypass_escape_condition) begin
          tmp_state_d = TMP_PERSISTENCE_OFF;
        end
      end

      default: begin
        tmp_state_d = TMP_PERSISTENCE_OFF;
      end
    endcase
  end

  // State register with asynchronous reset
  prim_flop #(
    .Width($bits(tmp_state_e)),
    .ResetValue(TMP_PERSISTENCE_OFF)
  ) u_tmp_state_flop (
    .clk_i  (tap_ctrl_i.tck),
    .rst_ni (tap_ctrl_i.trst_n),
    .d_i    (tmp_state_d),
    .q_o    (tmp_state_q_bits)
  );

  //--------------------------------------------------------------------------
  // Output Assignments
  //--------------------------------------------------------------------------

  // TMP controller status outputs
  assign persistence_mode_o = (tmp_state_q == TMP_PERSISTENCE_ON);

endmodule : jtag_tmp

