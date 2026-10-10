// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Buffer a vector so synthesis keeps the boundary.
//
// One sg13g2_buf_1 per bit.
module prim_buf #(
  parameter int Width = 1  // Bit width of the buffered vector.
) (
  input  logic [Width-1:0] in_i,  // Value to buffer.
  output logic [Width-1:0] out_o  // Buffered value.
);
  for (genvar i = 0; i < Width; i++) begin : gen_bit
    (* dont_touch = "true" *)
    sg13g2_buf_1 u_cell (
      .A       (in_i[i]),
      .X       (out_o[i])
    );
  end
endmodule
