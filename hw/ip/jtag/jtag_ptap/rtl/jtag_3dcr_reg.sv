// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG TAP 3DCR Register
//
//-----------------------------------------------------------------------------

module jtag_3dcr_reg
  import prim_jtag_pkg::*;
(
  /* verilator lint_off UNUSEDSIGNAL */
  // JTAG DR scan control interface
  input  jtag_scan_ctrl_t  scan_ctrl_i,
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,
  output logic             scan_out_o,

  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_tap_ctrl_t  tap_ctrl_i,
  /* verilator lint_on UNUSEDSIGNAL */

  // STAP control output (IEEE 1838)
  output logic  stap_sel_o
);
  logic unused_tap_ctrl;
  assign unused_tap_ctrl = tap_ctrl_i.tms;

  jtag_scan_ctrl_t  reg_scan_ctrl;
  logic             config_hold;
  logic             config_hold_sticky;
  logic rst_n_or_out, rst_n_gate;

  // Shadow flop: breaks the combinational loop through u_3dcr_scan_reg's
  // async reset pin.  Resets only on trst_n (hard reset), lags config_hold by
  // one TCK cycle.  The one-cycle gap is safe: scan_ctrl_i.rst_n cannot assert
  // within one TCK of an Update-DR write without multiple intermediate TAP
  // state transitions.
  prim_flop #(
    .Width     (1),
    .ResetValue(1'b0),
    .Negedge   (1'b1)
  ) u_config_hold_sticky_flop (
    .clk_i  (scan_ctrl_i.tck),
    .rst_ni (tap_ctrl_i.trst_n),
    .d_i    (config_hold),
    .q_o    (config_hold_sticky)
  );

  // 3DCR reset control — primitive gates ensure glitch-free reset path
  prim_or2 u_rst_n_or (
    .in0_i (config_hold_sticky),
    .in1_i (scan_ctrl_i.rst_n),
    .out_o (rst_n_or_out)
  );

  prim_and2 #(
    .Width(1)
  ) u_rst_n_and (
    .in0_i (tap_ctrl_i.trst_n),
    .in1_i (rst_n_or_out),
    .out_o (rst_n_gate)
  );

  always_comb begin
    reg_scan_ctrl       = scan_ctrl_i;
    reg_scan_ctrl.rst_n = rst_n_gate;
  end

  // STAP 3DCR control register
  prim_jtag_scan_reg #(
    .WIDTH(2),
    .RESET_VAL('0),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_3dcr_scan_reg (
    .scan_ctrl_i   (reg_scan_ctrl),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     ({stap_sel_o, config_hold}),
    .data_out_o    ({stap_sel_o, config_hold})
  );

endmodule : jtag_3dcr_reg
