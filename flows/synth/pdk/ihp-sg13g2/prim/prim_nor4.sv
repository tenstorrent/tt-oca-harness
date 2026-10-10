// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// NOR four inputs.
//
// Maps to one sg13g2_nor4_1.
module prim_nor4 (
  input  logic in0_i,  // Operand 0.
  input  logic in1_i,  // Operand 1.
  input  logic in2_i,  // Operand 2.
  input  logic in3_i,  // Operand 3.
  output logic out_o  // Gate output.
);
  (* dont_touch = "true" *)
  sg13g2_nor4_1 u_cell (
    .A       (in0_i),
    .B       (in1_i),
    .C       (in2_i),
    .D       (in3_i),
    .Y       (out_o)
  );
endmodule
