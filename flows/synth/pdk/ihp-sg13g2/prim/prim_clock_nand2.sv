// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// NAND two inputs on a clock or ring-oscillator path.
//
// Maps to one sg13g2_nand2_1.
module prim_clock_nand2 (
  input  logic a1_i,  // First operand.
  input  logic a2_i,  // Second operand.
  output logic y_o  // Gate output.
);
  (* dont_touch = "true" *)
  sg13g2_nand2_1 u_cell (
    .A       (a1_i),
    .B       (a2_i),
    .Y       (y_o)
  );
endmodule
