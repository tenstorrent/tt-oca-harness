// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG TMP Status Register
//
//-----------------------------------------------------------------------------

module jtag_tmp_status_reg
  import prim_jtag_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  // JTAG DR scan control interface
  input  jtag_scan_ctrl_t  scan_ctrl_i,
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,
  output logic             scan_out_o,

  // TMP controller state input
  input  logic             persistence_mode_i,    // TMP controller persistence mode

  // TMP status output
  output logic             bypass_escape_bit_o     // Bypass escape enable bit
);

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned REG_WIDTH = 2;  // TMP status register: 2 bits per IEEE 1149.1 Section 16.1

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  logic [REG_WIDTH-1:0] tmp_status_reg_q;  // TMP status register output (update register)

  //--------------------------------------------------------------------------
  // TMP Status Register
  //--------------------------------------------------------------------------
  // Per IEEE 1149.1 Section 16.1:
  // - Bit [1]: TMP-status bit (closest to TDI) - read-only, reflects TMP controller state
  // - Bit [0]: bypass-escape bit (closest to TDO) - user programmable
  // On capture: TMP-status captures persistence_mode_i, bypass-escape retains its value
  prim_jtag_scan_reg #(
    .WIDTH(REG_WIDTH),
    .RESET_VAL(2'b10),  // Default: bypass_escape=1, persistence=0
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

