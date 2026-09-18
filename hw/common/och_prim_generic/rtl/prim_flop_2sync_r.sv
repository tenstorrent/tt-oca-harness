// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 2-Flop Synchronizer (Reset)
//
//--------------------------------------------------
module prim_flop_2sync_r (
  input clk_i,
  input d_i,
  input rst_ni,
  output wire q_o
);

  logic q_d, q_dd;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (rst_ni == 1'b0) begin
      q_d  <= 1'b0;
      q_dd <= 1'b0;
    end else begin
      q_d  <= d_i;
      q_dd <= q_d;
    end
  end
  assign q_o = q_dd;

endmodule
