// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Select one of two clocks.
//
// Maps to one sg13g2_mux2_1; the FPGA parameter has no effect.
module prim_clock_mux2 #(
  parameter bit NoFpgaBufG = 1'b0  // Unused outside FPGA builds.
) (
  input  logic clk0_i,  // Clock selected while sel_i is low.
  input  logic clk1_i,  // Clock selected while sel_i is high.
  input  logic sel_i,  // Clock select.
  output logic clk_o  // Selected clock.
);
  (* dont_touch = "true" *)
  sg13g2_mux2_1 u_cell (
    .A0      (clk0_i),
    .A1      (clk1_i),
    .S       (sel_i),
    .X       (clk_o)
  );
endmodule
