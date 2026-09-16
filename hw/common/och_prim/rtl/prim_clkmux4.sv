// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-input Clock Multiplexer
//
//--------------------------------------------------
module prim_clkmux4 (
  input logic [3:0] i_clk,
  input logic [1:0] i_clksel,
  output logic o_clk
);

  wire [1:0] clk_mux_0;

  genvar i;

  generate
    for (i = 0; i < 2; i = i + 1) begin : gen_clk_mux_0
      prim_clock_mux2 clkmux_0 (
        .clk0_i (i_clk[2*i]),
        .clk1_i (i_clk[2*i+1]),
        .sel_i(i_clksel[0]),
        .clk_o  (clk_mux_0[i])
      );
    end
  endgenerate

  prim_clock_mux2 clkmux_1 (
    .clk0_i (clk_mux_0[0]),
    .clk1_i (clk_mux_0[1]),
    .sel_i(i_clksel[1]),
    .clk_o  (o_clk)
  );

endmodule
