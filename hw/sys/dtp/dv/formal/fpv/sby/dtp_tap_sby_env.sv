// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Environment of the tap task on the dtp formal top, read by that task beside dtp_sby_env.sv: an
// Update-IR loads an opcode the open-path model decodes as the RTL does. The frontend sizes a
// type cast's operand on its own, so the RTL's `T'(2 ** shift)` decode is 32 bits wide in the
// model and an opcode of 31 or more sets several instruction bits at once, among them the
// zero-length bypass that routes TDO around its falling-edge retimer. Bound to dtp by the
// statement at the end of this file.

`include "ocah_fv_macros.svh"

module dtp_tap_sby_env #(
  parameter int unsigned IR_WIDTH = 6
) (
  input logic                tck_i,
  input logic                trst_ni,
  input logic                ir_update_en_i,  // ir_scan_ctrl.update_en
  input logic [IR_WIDTH-1:0] ir_shift_i       // instruction_shift_reg_q_bits
);

  // The highest opcode the open-path frontend decodes as the RTL does.
  localparam logic [IR_WIDTH-1:0] OpenPathMaxOpcode = 6'h1E;

`ifdef FORMAL
  // verilog_format: off
  `OCAH_FV_ASSUME(asm_env_ir_open_path_decode_range,
                  `OCAH_FV_IMPLIES(ir_update_en_i, ir_shift_i <= OpenPathMaxOpcode),
                  tck_i, trst_ni)
  // verilog_format: on
`endif

endmodule : dtp_tap_sby_env

bind dtp dtp_tap_sby_env u_dtp_tap_sby_env (
  .tck_i          (jtag_ptap_client_tap_ctrl_i.tck),
  .trst_ni        (jtag_ptap_client_tap_ctrl_i.trst_n & pwr_on_rst_ni),
  .ir_update_en_i (u_jtag_intf_unit.u_jtag_ptap.ir_scan_ctrl.update_en),
  .ir_shift_i     (u_jtag_intf_unit.u_jtag_ptap.u_jtag_inst_reg.instruction_shift_reg_q_bits)
);
