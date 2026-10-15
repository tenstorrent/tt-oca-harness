// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Register one bit with an asynchronous active-low reset, for metastable inputs.
//
// The cell library has no metastability-hardened flop; this maps to one sg13g2_dfrbpq_1.
module prim_metastab_hardened_dffr (
  input  logic clk_i,  // Capture clock.
  input  logic d_i,  // Possibly asynchronous input.
  input  logic rst_ni,  // Asynchronous active-low reset.
  output logic q_o  // Registered value.
);
  (* dont_touch = "true" *)
  sg13g2_dfrbpq_1 u_cell (
    .CLK     (clk_i),
    .D       (d_i),
    .RESET_B (rst_ni),
    .Q       (q_o)
  );
endmodule
