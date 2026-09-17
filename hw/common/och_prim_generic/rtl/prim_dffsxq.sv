// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// DFF SXQ Flop
//
//--------------------------------------------------
module prim_dffsxq (
  input clk_i,
  input d_i,
  input set_ni,
  output wire q_o
);

  logic q_d;
  always_ff @(posedge clk_i or negedge set_ni) begin
    q_d <= ~set_ni ? 1'b1 : d_i;
  end

  assign q_o = q_d;

endmodule
