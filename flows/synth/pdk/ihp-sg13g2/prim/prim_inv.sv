// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Invert a vector bit by bit.
//
// One sg13g2_inv_1 per bit.
module prim_inv #(
  parameter int Width = 1  // Bit width of the inverted vector.
) (
  input  logic [Width-1:0] in_i,  // Value to invert.
  output logic [Width-1:0] out_o  // Inverted value.
);
  for (genvar i = 0; i < Width; i++) begin : gen_bit
    (* dont_touch = "true" *)
    sg13g2_inv_1 u_cell (
      .A       (in_i[i]),
      .Y       (out_o[i])
    );
  end
endmodule
