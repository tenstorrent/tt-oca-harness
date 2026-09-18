// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-Flop Synchronizer
//
//--------------------------------------------------
module prim_flop_3sync (
  input clk_i,
  input d_i,
  output wire q_o
);

  logic q_d, q_dd, q_ddd;

  always_ff @(posedge clk_i) begin
    q_d   <= d_i;
    q_dd  <= q_d;
    q_ddd <= q_dd;
  end

  assign q_o = q_ddd;
endmodule
