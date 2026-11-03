// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment for the smu_axi_xbar formal top: the reset model and the DFT test input.
// Bound to smu_axi_xbar by the statement at the end of this file and read only by the task file.
//
// The crossbar has one clock, so the reset is asserted at the first clk_i posedge and released
// there for the rest of the trace. The AXI handshake rules of the initiators and the targets are
// the shared checker's, bound in assume mode by smu_axi_xbar_axi_fv_bind.sv; the aperture inputs
// stay free at every step.

`include "ocah_fv_macros.svh"

module smu_axi_xbar_sby_env (
  input logic clk_i,   // Crossbar clock, the sampling edge of the assumptions.
  input logic rst_ni,  // Active-low crossbar reset that the reset model drives.
  input logic test_i   // DFT test enable of the crossbar, held low.
);

`ifdef FORMAL
  logic released_q = 1'b0;
  always @(posedge clk_i) released_q <= 1'b1;

  // verilog_format: off
  // The reset model: rst_ni low at the first sampling edge, high at every later one.
  asm_env_reset_released : assume property (@(posedge clk_i) rst_ni == released_q);
  // The proof covers functional operation, where the DFT test enable is low.
  `OCAH_FV_ASSUME(asm_env_test_mode_off, !test_i, clk_i, 1'b1)
  // verilog_format: on
`endif

endmodule : smu_axi_xbar_sby_env

bind smu_axi_xbar smu_axi_xbar_sby_env u_smu_axi_xbar_sby_env (
  .clk_i  (clk_i),
  .rst_ni (rst_ni),
  .test_i (test_i)
);
