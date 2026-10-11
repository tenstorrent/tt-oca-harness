// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR two inputs.
//
// Maps to one sg13g2_or2_1.
module prim_or2 (
  input  logic in0_i,  // Operand 0.
  input  logic in1_i,  // Operand 1.
  output logic out_o  // Gate output.
);
  (* dont_touch = "true" *)
  sg13g2_or2_1 u_cell (
    .A       (in0_i),
    .B       (in1_i),
    .X       (out_o)
  );
endmodule
