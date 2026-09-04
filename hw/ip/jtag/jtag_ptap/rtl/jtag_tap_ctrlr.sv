// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG TAP FSM
//
//-----------------------------------------------------------------------------

module jtag_tap_ctrlr
  import prim_jtag_pkg::*;
  import jtag_tap_pkg::*;
#(
  parameter bit TMP_ENABLE = 1  // Enables TMP controller functionality and instructions
) (
  // Standard JTAG input interface
  input  jtag_tap_ctrl_t          client_tap_ctrl_i,    // TAP control inputs (tms, trst_n, tck)

  // TMP controller inputs
  input  logic                    persistence_mode_i,   // TMP persistence mode (1=On, 0=Off)

  // RUNBIST instruction input
  input  logic                    runbist_i,             // RUNBIST instruction decoded

  // Internal JTAG interface
  output jtag_tap_ctrl_t          host_tap_ctrl_o,      // TAP control outputs (tms, trst_n, tck)

  // TDR scan interface
  output jtag_scan_ctrl_t         host_dr_scan_ctrl_o,  // DR scan control outputs
  output jtag_scan_ctrl_t         host_ir_scan_ctrl_o,  // IR scan control outputs

  // Debug and status signals
  output tap_state_e              current_state_o,

  // TDO output enable
  output logic                    tdo_oen_o
);

  //--------------------------------------------------------------------------
  // Internal signals
  //--------------------------------------------------------------------------
  tap_state_e current_state_q, next_state;
  logic [$bits(tap_state_e)-1:0] current_state_q_bits;

  assign current_state_q = tap_state_e'(current_state_q_bits);

  // TMS reset counter for fault state recovery (IEEE 1149.1 compliance)
  logic [2:0] tms_reset_counter_q, tms_reset_counter_d;

  // Internal control signals
  logic capture_dr, shift_dr, update_dr;
  logic capture_ir, shift_ir, update_ir;
  logic run_test_idle;
  logic test_logic_reset;

  //--------------------------------------------------------------------------
  // Three-Always Block Implementation (Moore State Machine)
  //--------------------------------------------------------------------------

  // Always block 1: State register with fault state recovery
  prim_flop #(
    .Width($bits(tap_state_e)),
    .ResetValue(TEST_LOGIC_RESET)
  ) u_current_state_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (next_state),
    .q_o    (current_state_q_bits)
  );

  prim_flop #(
    .Width(3),
    .ResetValue(3'b0)
  ) u_tms_reset_counter_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (tms_reset_counter_d),
    .q_o    (tms_reset_counter_q)
  );

  // Always block 2: Next state logic (combinational)
  always_comb begin
    next_state = current_state_q;  // Default: stay in current state

    // TMS reset counter logic (IEEE 1149.1: 5 consecutive TMS high -> TLR)
    if (client_tap_ctrl_i.tms) begin
      if (tms_reset_counter_q < 3'd5) begin
        tms_reset_counter_d = tms_reset_counter_q + 1'b1;
      end else begin
        tms_reset_counter_d = 3'd5;  // Saturate at 5
      end
    end else begin
      tms_reset_counter_d = 3'b0;  // Reset counter on TMS low
    end

    case (current_state_q)
      TEST_LOGIC_RESET: begin
        if (!client_tap_ctrl_i.tms) next_state = RUN_TEST_IDLE;
        else next_state = TEST_LOGIC_RESET;
      end

      RUN_TEST_IDLE: begin
        if (client_tap_ctrl_i.tms) next_state = SELECT_DR_SCAN;
        else next_state = RUN_TEST_IDLE;
      end

      SELECT_DR_SCAN: begin
        if (!client_tap_ctrl_i.tms) next_state = CAPTURE_DR;
        else next_state = SELECT_IR_SCAN;
      end

      CAPTURE_DR: begin
        if (!client_tap_ctrl_i.tms) next_state = SHIFT_DR;
        else next_state = EXIT1_DR;
      end

      SHIFT_DR: begin
        if (client_tap_ctrl_i.tms) next_state = EXIT1_DR;
        else next_state = SHIFT_DR;
      end

      EXIT1_DR: begin
        if (!client_tap_ctrl_i.tms) next_state = PAUSE_DR;
        else next_state = UPDATE_DR;
      end

      PAUSE_DR: begin
        if (client_tap_ctrl_i.tms) next_state = EXIT2_DR;
        else next_state = PAUSE_DR;
      end

      EXIT2_DR: begin
        if (!client_tap_ctrl_i.tms) next_state = SHIFT_DR;
        else next_state = UPDATE_DR;
      end

      UPDATE_DR: begin
        if (!client_tap_ctrl_i.tms) next_state = RUN_TEST_IDLE;
        else next_state = SELECT_DR_SCAN;
      end

      SELECT_IR_SCAN: begin
        if (!client_tap_ctrl_i.tms) next_state = CAPTURE_IR;
        else next_state = TEST_LOGIC_RESET;
      end

      CAPTURE_IR: begin
        if (!client_tap_ctrl_i.tms) next_state = SHIFT_IR;
        else next_state = EXIT1_IR;
      end

      SHIFT_IR: begin
        if (client_tap_ctrl_i.tms) next_state = EXIT1_IR;
        else next_state = SHIFT_IR;
      end

      EXIT1_IR: begin
        if (!client_tap_ctrl_i.tms) next_state = PAUSE_IR;
        else next_state = UPDATE_IR;
      end

      PAUSE_IR: begin
        if (client_tap_ctrl_i.tms) next_state = EXIT2_IR;
        else next_state = PAUSE_IR;
      end

      EXIT2_IR: begin
        if (!client_tap_ctrl_i.tms) next_state = SHIFT_IR;
        else next_state = UPDATE_IR;
      end

      UPDATE_IR: begin
        if (!client_tap_ctrl_i.tms) next_state = RUN_TEST_IDLE;
        else next_state = SELECT_DR_SCAN;
      end

      default: begin
        // Error recovery: unknown state, go to Test-Logic-Reset
        next_state = TEST_LOGIC_RESET;
      end
    endcase
  end

  // Always block 3: Output logic (Moore machine outputs)
  always_comb begin
    // Default values
    update_dr     = 1'b0;
    update_ir     = 1'b0;
    run_test_idle = 1'b0;

    // Generate control signals based on current state
    case (current_state_q)
      UPDATE_DR:     update_dr  = 1'b1;
      UPDATE_IR:     update_ir  = 1'b1;
      RUN_TEST_IDLE: run_test_idle = 1'b1;
      default: begin
      end
    endcase
  end

  // Combinational next-value logic for negedge-clocked control signals
  logic capture_dr_d, shift_dr_d, capture_ir_d, shift_ir_d, test_logic_reset_d, tdo_oen_d;

  always_comb begin
    capture_dr_d       = (current_state_q == CAPTURE_DR);
    shift_dr_d         = (current_state_q == SHIFT_DR);
    capture_ir_d       = (current_state_q == CAPTURE_IR);
    shift_ir_d         = (current_state_q == SHIFT_IR);
    test_logic_reset_d = (current_state_q == TEST_LOGIC_RESET);
    tdo_oen_d          = (current_state_q == SHIFT_DR) || (current_state_q == SHIFT_IR);
  end

  prim_flop #(
    .Width(1),
    .ResetValue(1'b0),
    .Negedge(1'b1)
  ) u_capture_dr_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (capture_dr_d),
    .q_o    (capture_dr)
  );

  prim_flop #(
    .Width(1),
    .ResetValue(1'b0),
    .Negedge(1'b1)
  ) u_shift_dr_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (shift_dr_d),
    .q_o    (shift_dr)
  );

  prim_flop #(
    .Width(1),
    .ResetValue(1'b0),
    .Negedge(1'b1)
  ) u_capture_ir_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (capture_ir_d),
    .q_o    (capture_ir)
  );

  prim_flop #(
    .Width(1),
    .ResetValue(1'b0),
    .Negedge(1'b1)
  ) u_shift_ir_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (shift_ir_d),
    .q_o    (shift_ir)
  );

  prim_flop #(
    .Width(1),
    .ResetValue(1'b1),
    .Negedge(1'b1)
  ) u_test_logic_reset_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (test_logic_reset_d),
    .q_o    (test_logic_reset)
  );

  prim_flop #(
    .Width(1),
    .ResetValue(1'b0),
    .Negedge(1'b1)
  ) u_tdo_oen_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (tdo_oen_d),
    .q_o    (tdo_oen_o)
  );

  //--------------------------------------------------------------------------
  // Pass-Through Logic
  //--------------------------------------------------------------------------

  // Pass through TAP control signals to host interface
  assign host_tap_ctrl_o = client_tap_ctrl_i;

  //--------------------------------------------------------------------------
  // Output Port Assignments
  //--------------------------------------------------------------------------

  // Data register scan interface
  assign host_dr_scan_ctrl_o.tck              = client_tap_ctrl_i.tck;
  assign host_dr_scan_ctrl_o.rst_n            = !test_logic_reset;
  assign host_dr_scan_ctrl_o.chrst_n          = TMP_ENABLE ? !test_logic_reset || persistence_mode_i : !test_logic_reset;
  assign host_dr_scan_ctrl_o.select           = current_state_q inside {EXIT2_DR, EXIT1_DR, SHIFT_DR, PAUSE_DR, SELECT_IR_SCAN, UPDATE_DR, CAPTURE_DR, SELECT_DR_SCAN};
  assign host_dr_scan_ctrl_o.capture_en       = capture_dr;
  assign host_dr_scan_ctrl_o.shift_en         = shift_dr;
  assign host_dr_scan_ctrl_o.update_en        = update_dr;
  assign host_dr_scan_ctrl_o.run_test_idle    = run_test_idle;
  assign host_dr_scan_ctrl_o.test_logic_reset = test_logic_reset;
  assign host_dr_scan_ctrl_o.runbist          = runbist_i;

  // Instruction register scan interface
  assign host_ir_scan_ctrl_o.tck              = client_tap_ctrl_i.tck;
  assign host_ir_scan_ctrl_o.rst_n            = !test_logic_reset;
  assign host_ir_scan_ctrl_o.chrst_n          = TMP_ENABLE ? !test_logic_reset || persistence_mode_i : !test_logic_reset;
  assign host_ir_scan_ctrl_o.select           = current_state_q inside {EXIT2_IR, EXIT1_IR, SHIFT_IR, PAUSE_IR, RUN_TEST_IDLE, UPDATE_IR, CAPTURE_IR, TEST_LOGIC_RESET};
  assign host_ir_scan_ctrl_o.capture_en       = capture_ir;
  assign host_ir_scan_ctrl_o.shift_en         = shift_ir;
  assign host_ir_scan_ctrl_o.update_en        = update_ir;
  assign host_ir_scan_ctrl_o.run_test_idle    = run_test_idle;
  assign host_ir_scan_ctrl_o.test_logic_reset = test_logic_reset;
  assign host_ir_scan_ctrl_o.runbist          = runbist_i;

  //--------------------------------------------------------------------------
  // Debug and Status Outputs
  //--------------------------------------------------------------------------
  assign current_state_o       = current_state_q;

endmodule : jtag_tap_ctrlr
