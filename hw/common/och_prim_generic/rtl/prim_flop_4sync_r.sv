// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-Flop Synchronizer (Reset)
//
//--------------------------------------------------
module prim_flop_4sync_r (
  input clk_i,
  input d_i,
  input rst_ni,
  output wire q_o
);

  logic q_d, q_dd, q_ddd, q_dddd;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (rst_ni == 1'b0) begin
      q_d <= 1'b0;
      q_dd <= 1'b0;
      q_ddd <= 1'b0;
      q_dddd <= 1'b0;
    end else begin
      q_d <= d_i;
      q_dd <= q_d;
      q_ddd <= q_dd;
      q_dddd <= q_ddd;
    end
  end
  assign q_o = q_dddd;

endmodule
