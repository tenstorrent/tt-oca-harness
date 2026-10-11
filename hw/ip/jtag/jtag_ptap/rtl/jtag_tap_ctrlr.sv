// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Advance the IEEE 1149.1 TAP FSM and generate IR/DR scan controls.
//
// Tracks tap_state_e from TMS on rising TCK, passes the TAP control through to the host,
// and drives IR and DR scan controls.
// Capture, shift and Test-Logic-Reset controls are registered on falling TCK; update and
// Run-Test/Idle controls decode the current state.
// With TMP_ENABLE, persistence_mode_i keeps the scan chrst_n released through
// Test-Logic-Reset; runbist_i is forwarded to both scan controls.
// tdo_oen_o enables TDO in Shift-IR and Shift-DR.

module jtag_tap_ctrlr
  import prim_jtag_pkg::jtag_tap_ctrl_t;
  import prim_jtag_pkg::jtag_scan_ctrl_t;
  import jtag_tap_pkg::tap_state_e;
  import jtag_tap_pkg::TEST_LOGIC_RESET;
  import jtag_tap_pkg::RUN_TEST_IDLE;
  import jtag_tap_pkg::SELECT_DR_SCAN;
  import jtag_tap_pkg::CAPTURE_DR;
  import jtag_tap_pkg::SELECT_IR_SCAN;
  import jtag_tap_pkg::SHIFT_DR;
  import jtag_tap_pkg::EXIT1_DR;
  import jtag_tap_pkg::PAUSE_DR;
  import jtag_tap_pkg::UPDATE_DR;
  import jtag_tap_pkg::EXIT2_DR;
  import jtag_tap_pkg::CAPTURE_IR;
  import jtag_tap_pkg::SHIFT_IR;
  import jtag_tap_pkg::EXIT1_IR;
  import jtag_tap_pkg::PAUSE_IR;
  import jtag_tap_pkg::UPDATE_IR;
  import jtag_tap_pkg::EXIT2_IR;
#(
  parameter bit TMP_ENABLE = 1          // Lets persistence_mode_i hold chrst_n released through
                                        // Test-Logic-Reset.
) (
  input  jtag_tap_ctrl_t          client_tap_ctrl_i,  // TAP control inputs (tms, trst_n, tck);
                                                      // trst_n asynchronously resets the FSM to
                                                      // Test-Logic-Reset.

  input  logic                    persistence_mode_i,  // TMP persistence mode (1=On, 0=Off); when
                                                       // on with TMP_ENABLE, chrst_n stays high in
                                                       // Test-Logic-Reset.

  input  logic                    runbist_i,  // RUNBIST instruction decoded; forwarded to the
                                              // runbist field of both scan controls.

  output jtag_tap_ctrl_t          host_tap_ctrl_o,  // TAP control outputs (tms, trst_n, tck),
                                                    // passed through unchanged from
                                                    // client_tap_ctrl_i.

  output jtag_scan_ctrl_t         host_dr_scan_ctrl_o,  // DR scan control outputs; rst_n is low in
                                                        // Test-Logic-Reset.
  output jtag_scan_ctrl_t         host_ir_scan_ctrl_o,  // IR scan control outputs; rst_n is low in
                                                        // Test-Logic-Reset.

  output tap_state_e              current_state_o,  // Current state (Debug and status signals).

  output logic                    tdo_oen_o  // Active-high TDO output enable, set in Shift-DR and
                                             // Shift-IR; registered on the falling TCK edge and
                                             // cleared by trst_n.
);

  //--------------------------------------------------------------------------
  // Internal signals
  //--------------------------------------------------------------------------
  tap_state_e current_state_q, next_state;
  logic [$bits(tap_state_e)-1:0] current_state_q_bits;

  assign current_state_q = tap_state_e'(current_state_q_bits);

  // Internal control signals
  logic capture_dr, shift_dr, update_dr;
  logic capture_ir, shift_ir, update_ir;
  logic run_test_idle;
  logic test_logic_reset;

  //--------------------------------------------------------------------------
  // Three-Always Block Implementation (Moore State Machine)
  //--------------------------------------------------------------------------

  // Always block 1: State register
  prim_flop #(
    .Width($bits(tap_state_e)),
    .ResetValue(TEST_LOGIC_RESET)
  ) u_current_state_flop (
    .clk_i  (client_tap_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (next_state),
    .q_o    (current_state_q_bits)
  );

  // Always block 2: Next state logic (combinational)
  always_comb begin
    next_state = current_state_q;  // Default: stay in current state

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
