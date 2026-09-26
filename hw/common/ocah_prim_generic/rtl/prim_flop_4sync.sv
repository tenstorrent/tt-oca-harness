// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-Flop Synchronizer
//
//--------------------------------------------------
module prim_flop_4sync (
  input clk_i,
  input d_i,
  output wire q_o
);

  logic q_d, q_dd, q_ddd, q_dddd;

  always_ff @(posedge clk_i) begin
    q_d    <= d_i;
    q_dd   <= q_d;
    q_ddd  <= q_dd;
    q_dddd <= q_ddd;
  end

  assign q_o = q_dddd;
endmodule
