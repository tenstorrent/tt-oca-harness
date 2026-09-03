// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG Bypass Register
//
//-----------------------------------------------------------------------------

module jtag_byp_reg
  import prim_jtag_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  // JTAG DR scan control interface
  input  jtag_scan_ctrl_t  scan_ctrl_i,
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,
  output logic             scan_out_o
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
