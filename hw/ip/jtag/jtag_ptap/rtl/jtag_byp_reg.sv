// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement the one-bit IEEE 1149.1 bypass TDR on the DR scan path.
//
// Captures 0 and shifts a single bit between scan_in_i and scan_out_o under scan_ctrl_i.

module jtag_byp_reg
  import prim_jtag_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o   // Scan data out (TDO).
);

  //--------------------------------------------------------------------------
  // Bypass Register Sequential Logic
  //--------------------------------------------------------------------------

  // Single bit bypass register
  // Per IEEE 1149.1 Section 10.1.1: loads 0 on capture, shifts on shift
  prim_jtag_scan_reg #(
    .WIDTH(1),
    .RESET_VAL('0),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_byp_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     ('0),
    /* verilator lint_off PINCONNECTEMPTY */
    .data_out_o    (/* UNUSED */)
    /* verilator lint_on PINCONNECTEMPTY */
  );


endmodule : jtag_byp_reg
