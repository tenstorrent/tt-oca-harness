// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement a one-bit inverted bypass TDR on the DR scan path.
//
// Returns the complement of the shifted bit between scan_in_i and scan_out_o under
// scan_ctrl_i; the bit captures 0, so scan_out_o reads 1 after Capture-DR.

module jtag_inv_byp_reg
  import prim_jtag_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o   // Inverted scan data out (TDO).
);

  //--------------------------------------------------------------------------
  // Inverted Bypass Register Sequential Logic
  //--------------------------------------------------------------------------

  logic bypass_out;

  // Single bit bypass register
  // Per IEEE 1149.1 Section 10.1.1: loads 0 on capture, shifts on shift
  prim_jtag_scan_reg #(
    .WIDTH(1),
    .RESET_VAL('0),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_inv_byp_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (bypass_out),
    .data_in_i     ('0),
    /* verilator lint_off PINCONNECTEMPTY */
    .data_out_o    (/* UNUSED */)
    /* verilator lint_on PINCONNECTEMPTY */
  );

  // Inverted output (inverted bypass)
  assign scan_out_o = ~bypass_out;

endmodule : jtag_inv_byp_reg

