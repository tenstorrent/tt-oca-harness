// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement the TMP status TDR for persistence mode and bypass-escape enable.
//
// Captures persistence_mode_i into bit 1 and the current bypass-escape value into bit 0, the
// bit nearest TDO, and updates bypass_escape_bit_o on the falling TCK edge of Update-DR.
// bypass_escape_bit_o resets low on the scan-control reset.
// bypass_escape_bit_o feeds jtag_tmp so BYPASS can leave persistence-on when set.

module jtag_tmp_status_reg
  import prim_jtag_pkg::jtag_scan_ctrl_t;
(
  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o,  // Scan data out (TDO).

  input  logic             persistence_mode_i,  // TMP controller persistence mode, captured into
                                                // bit 1.

  output logic             bypass_escape_bit_o  // Bypass escape enable bit; bit 0 of the update
                                                // register, reset low.
);

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned RegWidth = 2;  // TMP status register: 2 bits per IEEE 1149.1 Section 16.1

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  logic [RegWidth-1:0] tmp_status_reg_q;  // TMP status register output (update register)

  //--------------------------------------------------------------------------
  // TMP Status Register
  //--------------------------------------------------------------------------
  // Per IEEE 1149.1 Section 16.1:
  // - Bit [1]: TMP-status bit (closest to TDI) - read-only, reflects TMP controller state
  // - Bit [0]: bypass-escape bit (closest to TDO) - user programmable
  // On capture: TMP-status captures persistence_mode_i, bypass-escape retains its value
  prim_jtag_scan_reg #(
    .WIDTH(RegWidth),
    .RESET_VAL(2'b10),  // bypass_escape (bit 0) resets to 0; bit 1 is overwritten at Capture-DR
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_tmp_status_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     ({persistence_mode_i, tmp_status_reg_q[0]}),  // Capture: TMP-status from controller, bypass-escape retains value
    .data_out_o    (tmp_status_reg_q)
  );

  // Extract bypass-escape bit for output to TMP controller
  // Read from update register (data_out_o) which holds the stable value after update
  assign bypass_escape_bit_o = tmp_status_reg_q[0];  // bypass-escape bit (bit 0, closest to TDO)

endmodule : jtag_tmp_status_reg

