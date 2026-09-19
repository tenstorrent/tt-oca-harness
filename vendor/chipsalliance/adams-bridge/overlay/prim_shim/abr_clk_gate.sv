// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// ABR ICG name is abr_clk_gate (`ABR_ICG). TECH_SPECIFIC_ICG skips the latch
// in abr_icg.sv. This module instantiates prim_clkgater so `-t synth` picks
// the foundry cell. te is DFT test-enable; it forces the clock through.
module abr_clk_gate (
  input  logic clk,
  input  logic en,
  input  logic te,
  output logic clk_cg
);

  prim_clkgater u_clkgater (
    .i_clk(clk),
    .i_en (en),
    .i_te (te),
    .o_clk(clk_cg)
  );

endmodule
