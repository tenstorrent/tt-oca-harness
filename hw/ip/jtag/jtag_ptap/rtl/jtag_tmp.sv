// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG Test Mode Persistence (TMP) Controller
//
//-----------------------------------------------------------------------------

module jtag_tmp
  import prim_jtag_pkg::*;
  import jtag_tmp_pkg::*;
(
  // TAP control interface
  input  jtag_tap_ctrl_t  tap_ctrl_i,

  // IR update signal (from TAP controller)
  input  logic             update_ir_i,

  // Test logic reset (from TAP controller state)
  input  logic             test_logic_reset_i,

  // Centralized instruction decoding inputs (from instruction register)
  input  logic             clamp_hold_selected_i,      // CLAMP_HOLD instruction selected
  input  logic             clamp_release_selected_i,   // CLAMP_RELEASE instruction selected
  input  logic             bypass_selected_i,          // BYPASS instruction selected

  // TMP controller status outputs
  output logic             persistence_mode_o,     // 1 = Persistence-On, 0 = Persistence-Off

  // TMP status register input
  input  logic             bypass_escape_enable_i // Bypass escape enable input from status register
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

