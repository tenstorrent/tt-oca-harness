// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Shift the JTAG instruction register and decode the current opcode.
//
// Captures 6'b000001 and shifts the IR on the IR scan path between scan_in_i and scan_out_o.
// inst_decoded_o is the decoded instruction enum consumed by PTAP muxes, one-hot in the
// opcode, loaded on the falling TCK edge while update_en is high and reset to
// DefaultInstruction (IDCODE).

module jtag_inst_reg
  import prim_jtag_pkg::*;
  import jtag_inst_reg_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o,  // Scan data out (TDO).

  output jtag_instruction_decoded_e  inst_decoded_o  // Current decoded instruction, one-hot in the
                                                     // opcode.
);
  // Tie off unused fields to satisfy lint
  logic unused_scan_ctrl;
  assign unused_scan_ctrl = ^{scan_ctrl_i.runbist,
                                scan_ctrl_i.test_logic_reset,
                                scan_ctrl_i.run_test_idle,
                                scan_ctrl_i.select,
                                scan_ctrl_i.chrst_n};

  //--------------------------------------------------------------------------
  // Internal Registers
  //--------------------------------------------------------------------------

  // Instruction register (holds current active instruction)
  jtag_instruction_decoded_e instruction_reg_q;
  logic [$bits(jtag_instruction_decoded_e)-1:0] instruction_reg_q_bits;

  // Instruction shift register (used during capture/shift operations)
  jtag_instruction_e instruction_shift_reg_q;
  logic [$bits(jtag_instruction_e)-1:0] instruction_shift_reg_q_bits;

  assign instruction_reg_q = jtag_instruction_decoded_e'(instruction_reg_q_bits);
  assign instruction_shift_reg_q = jtag_instruction_e'(instruction_shift_reg_q_bits);

  //--------------------------------------------------------------------------
  // Instruction Register Sequential Logic
  //--------------------------------------------------------------------------

  // Instruction register - updated on update_ir (negative edge for parallel output)
  prim_flop #(
    .Width($bits(jtag_instruction_decoded_e)),
    .ResetValue(DefaultInstruction),
    .Negedge(1'b1)
  ) u_instruction_reg_flop (
    .clk_i  (scan_ctrl_i.tck),
    .rst_ni (scan_ctrl_i.rst_n),
    .d_i    (scan_ctrl_i.update_en ? jtag_instruction_decoded_e'(2 ** instruction_shift_reg_q) : instruction_reg_q),
    .q_o    (instruction_reg_q_bits)
  );

  // Instruction shift register - used for capture and shift operations
  // Combinational next-value logic for shift register
  jtag_instruction_e instruction_shift_reg_d;
  always_comb begin
    if (scan_ctrl_i.capture_en) begin
      // Capture: Per IEEE 1149.1 Section 7.2.1, lower 2 bits must be 2'b01
      instruction_shift_reg_d = jtag_instruction_e'(1'b1);
    end else if (scan_ctrl_i.shift_en) begin
      // Shift: Shift in new instruction bit from scan input
      // Per IEEE 1149.1, LSB is shifted in first
      instruction_shift_reg_d = jtag_instruction_e'({
        scan_in_i, instruction_shift_reg_q[IrWidth-1:1]
      });
    end else begin
      instruction_shift_reg_d = instruction_shift_reg_q;
    end
  end

  prim_flop #(
    .Width(IrWidth),
    .ResetValue(BYPASS_ALT_INSTR)
  ) u_instruction_shift_reg_flop (
    .clk_i  (scan_ctrl_i.tck),
    .rst_ni (scan_ctrl_i.rst_n),
    .d_i    (instruction_shift_reg_d),
    .q_o    (instruction_shift_reg_q_bits)
  );

  //--------------------------------------------------------------------------
  // Output Assignments
  //--------------------------------------------------------------------------

  // Scan data output - LSB of shift register during shift operations
  assign scan_out_o = instruction_shift_reg_q[0];

  // Decoded instruction output - current active instruction
  assign inst_decoded_o = instruction_reg_q;

endmodule : jtag_inst_reg
