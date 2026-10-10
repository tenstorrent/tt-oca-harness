// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// XNOR two vectors bit by bit.
//
// One sg13g2_xnor2_1 per bit.
module prim_xnor2 #(
  parameter int Width = 1  // Bit width of the operands and the result.
) (
  input  logic [Width-1:0] in0_i,  // Operand 0.
  input  logic [Width-1:0] in1_i,  // Operand 1.
  output logic [Width-1:0] out_o  // Gate output.
);
  for (genvar i = 0; i < Width; i++) begin : gen_bit
    (* dont_touch = "true" *)
    sg13g2_xnor2_1 u_cell (
      .A       (in0_i[i]),
      .B       (in1_i[i]),
      .Y       (out_o[i])
    );
  end
endmodule
