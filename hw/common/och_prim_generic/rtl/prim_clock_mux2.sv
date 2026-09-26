// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Mux clk0_i and clk1_i onto clk_o with plain logic.
//
// Drive clk_o from clk1_i when sel_i is high and clk0_i when sel_i is low. Model the mux
// with logic operations for GTECH runs. NoFpgaBufG serves no function in this generic
// model and exists for API compatibility with FPGA-buffering variants.

module prim_clock_mux2 #(
  parameter bit NoFpgaBufG = 1'b0  // Unused in the generic model; FPGA flows may consume it.
) (
  input        clk0_i,  // Clock selected when sel_i is low.
  input        clk1_i,  // Clock selected when sel_i is high.
  input        sel_i,   // Selects clk1_i when high, clk0_i when low.
  output logic clk_o    // Muxed clock.
);
  // We model the mux with logic operations for GTECH runs.
  assign clk_o = (sel_i & clk1_i) | (~sel_i & clk0_i);

  // make sure sel is never X (including during reset)
  // need to use ##1 as this could break with inverted clocks that
  // start with a rising edge at the beginning of the simulation.

  // `OCAH_OT_ASSERT(selKnown0, ##1 !$isunknown(sel_i), clk0_i, 0)
  // `OCAH_OT_ASSERT(selKnown1, ##1 !$isunknown(sel_i), clk1_i, 0)

endmodule : prim_clock_mux2
