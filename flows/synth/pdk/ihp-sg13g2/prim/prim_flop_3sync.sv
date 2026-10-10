// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize one bit into the clk_i domain through 3 flop stages without reset.
//
// Each stage is an sg13g2_dfrbpq_1 with its reset tied inactive.
module prim_flop_3sync (
  input  logic clk_i,  // Destination clock.
  input  logic d_i,  // Asynchronous input.
  output logic q_o  // Synchronized output.
);
  logic [2:0] stage;

  (* dont_touch = "true" *)
  sg13g2_dfrbpq_1 u_stage_0 (
    .CLK     (clk_i),
    .D       (d_i),
    .RESET_B (1'b1),
    .Q       (stage[0])
  );

  (* dont_touch = "true" *)
  sg13g2_dfrbpq_1 u_stage_1 (
    .CLK     (clk_i),
    .D       (stage[0]),
    .RESET_B (1'b1),
    .Q       (stage[1])
  );

  (* dont_touch = "true" *)
  sg13g2_dfrbpq_1 u_stage_2 (
    .CLK     (clk_i),
    .D       (stage[1]),
    .RESET_B (1'b1),
    .Q       (stage[2])
  );

  assign q_o = stage[2];
endmodule
