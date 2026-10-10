// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize one bit into the clk_i domain through 3 flop stages with an asynchronous set.
//
// Each stage is an sg13g2_sdfbbp_1 using its set input.
module prim_flop_3sync_s (
  input  logic clk_i,  // Destination clock.
  input  logic d_i,  // Asynchronous input.
  input  logic set_ni,  // Asynchronous active-low set; sets every stage.
  output logic q_o  // Synchronized output.
);
  logic [2:0] stage;

  (* dont_touch = "true" *)
  sg13g2_sdfbbp_1 u_stage_0 (
    .CLK     (clk_i),
    .D       (d_i),
    .SCD     (1'b0),
    .SCE     (1'b0),
    .RESET_B (1'b1),
    .SET_B   (set_ni),
    .Q       (stage[0]),
    .Q_N     ()
  );

  (* dont_touch = "true" *)
  sg13g2_sdfbbp_1 u_stage_1 (
    .CLK     (clk_i),
    .D       (stage[0]),
    .SCD     (1'b0),
    .SCE     (1'b0),
    .RESET_B (1'b1),
    .SET_B   (set_ni),
    .Q       (stage[1]),
    .Q_N     ()
  );

  (* dont_touch = "true" *)
  sg13g2_sdfbbp_1 u_stage_2 (
    .CLK     (clk_i),
    .D       (stage[1]),
    .SCD     (1'b0),
    .SCE     (1'b0),
    .RESET_B (1'b1),
    .SET_B   (set_ni),
    .Q       (stage[2]),
    .Q_N     ()
  );

  assign q_o = stage[2];
endmodule
