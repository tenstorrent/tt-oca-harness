// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// ABR ICG name is abr_clk_gate (`ABR_ICG). TECH_SPECIFIC_ICG skips the latch
// in abr_icg.sv. This module instantiates prim_clock_gating so `-t synth` picks
// the foundry cell. te is DFT test-enable; it forces the clock through.
module abr_clk_gate (
  input  logic clk,
  input  logic en,
  input  logic te,
  output logic clk_cg
);

  prim_clock_gating u_clkgater (
    .clk_i(clk),
    .en_i (en),
    .test_en_i (te),
    .clk_o(clk_cg)
  );

endmodule
