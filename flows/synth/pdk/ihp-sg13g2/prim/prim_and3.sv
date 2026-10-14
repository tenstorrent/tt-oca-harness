// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// AND three inputs.
//
// Maps to one sg13g2_and3_1.
module prim_and3 (
  input  logic in0_i,  // Operand 0.
  input  logic in1_i,  // Operand 1.
  input  logic in2_i,  // Operand 2.
  output logic out_o  // Gate output.
);
  (* dont_touch = "true" *)
  sg13g2_and3_1 u_cell (
    .A       (in0_i),
    .B       (in1_i),
    .C       (in2_i),
    .X       (out_o)
  );
endmodule
