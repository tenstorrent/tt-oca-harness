// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Register a vector without reset.
//
// The cell library has no flop without reset, so each bit is an sg13g2_dfrbpq_1 with its reset
// tied inactive.
module prim_flop_no_rst #(
  parameter int Width = 1  // Bit width of the register.
) (
  input  logic             clk_i,  // Capture clock.
  input  logic [Width-1:0] d_i,  // Next value.
  output logic [Width-1:0] q_o  // Registered value.
);
  for (genvar i = 0; i < Width; i++) begin : gen_bit
    (* dont_touch = "true" *)
    sg13g2_dfrbpq_1 u_cell (
      .CLK     (clk_i),
      .D       (d_i[i]),
      .RESET_B (1'b1),
      .Q       (q_o[i])
    );
  end
endmodule
