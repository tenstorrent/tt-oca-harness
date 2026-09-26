// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Select one of four clocks with clksel_i.
//
// Drive clk_o with clk_i[clksel_i] combinatorially.
// Keep clksel_i glitch-free; the mux itself does not hazard-qualify the select.

module prim_clkmux4 (
  input logic [3:0] clk_i,  // Four clock inputs.
  input logic [1:0] clksel_i,  // Selects which clk_i bit drives clk_o.
  output logic clk_o  // Selected clock.
);

  wire [1:0] clk_mux_0;

  genvar i;

  generate
    for (i = 0; i < 2; i = i + 1) begin : gen_clk_mux_0
      prim_clock_mux2 u_clkmux_0 (
        .clk0_i (clk_i[2*i]),
        .clk1_i (clk_i[2*i+1]),
        .sel_i(clksel_i[0]),
        .clk_o  (clk_mux_0[i])
      );
    end
  endgenerate

  prim_clock_mux2 u_clkmux_1 (
    .clk0_i (clk_mux_0[0]),
    .clk1_i (clk_mux_0[1]),
    .sel_i(clksel_i[1]),
    .clk_o  (clk_o)
  );

endmodule
