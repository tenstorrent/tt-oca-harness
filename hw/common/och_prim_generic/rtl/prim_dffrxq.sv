// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// DFF RXQ Flop
//
//--------------------------------------------------
module prim_dffrxq (
  input clk_i,
  input d_i,
  input rst_ni,
  output wire q_o
);

  logic q_d;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (rst_ni == 1'b0) begin
      q_d <= 1'b0;
    end else begin
      q_d <= d_i;
    end
  end

  assign q_o = q_d;

endmodule
