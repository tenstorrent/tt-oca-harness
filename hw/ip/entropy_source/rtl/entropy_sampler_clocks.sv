// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mux and ripple-divide per-lane sample clocks for NRINGS noise generators.
//
// Each generator selects external sample_clk_i or the shared ring oscillator's shared_clk_i,
// then divides by powers of two from ÷1 through ÷32.

module entropy_sampler_clocks #(
  parameter int unsigned NRINGS = 12  // Ring-oscillator lane count.
) (
  input       logic                   clk_i,  // System clock; not used in this module.
  input       logic                   rst_ni,  // Active-low asynchronous reset of the ripple
                                               // dividers.
  input       logic                   sample_clk_i,  // External sample clock for lanes whose
                                                     // sample_clk_select_i bit is low.
  input       logic [NRINGS-1:0]      sample_clk_select_i,  // Per-lane clock source: high for the
                                                            // shared ring oscillator, low for
                                                            // sample_clk_i; change only while that
                                                            // lane's sample-clock enable is low.
  input       logic                   shared_clk_i,  // Shared ring-oscillator output,
                                                     // asynchronous.
  input       logic [NRINGS-1:0][4:0] sample_clk_divide_i,  // Per-lane divide exponent: 0-5 divide
                                                            // by 1 to 32, other values divide by 4;
                                                            // change only while that lane's
                                                            // sample-clock enable is low.
  output      logic [NRINGS-1:0]      sample_clk_o  // Per-lane selected and divided sample clock
                                                    // for the noise sampler's sampling flop.
);

  /////////////
  // Signals
  /////////////

  logic [NRINGS-1:0]      selected_clk;
  logic [NRINGS-1:0][5:0] sample_clk_divided;
  logic [NRINGS-1:0]      div_lo_clk;
  logic [NRINGS-1:0]      div_hi_clk;

  /////////////////
  // Sub-instances
  /////////////////

  // Clock-cell selects are not glitch-free. sample_clk_select_i[i] and
  // sample_clk_divide_i[i] change only while lane i's sample-clock enable is low.
  for (genvar i = 0; i < NRINGS; i++) begin : gen_sampler_clk
    logic       div_hi_en;
    logic       div_hi_sel;
    logic [1:0] div_lo_sel;

    prim_clock_mux2 u_sample_clk_src_mux (
      .clk0_i(sample_clk_i),
      .clk1_i(shared_clk_i),
      .sel_i (sample_clk_select_i[i]),
      .clk_o (selected_clk[i])
    );

    entropy_ripple_divider #(
      .NUM_STAGES(5)
    ) u_sample_clk_divider (
      .rst_ni (rst_ni),
      .clk_i  (selected_clk[i]),
      .div_o  (sample_clk_divided[i])
    );

    always_comb begin
      div_hi_en  = 1'b0;
      div_hi_sel = 1'b0;
      div_lo_sel = 2'd2;
      unique case (sample_clk_divide_i[i])
        5'd0, 5'd1, 5'd2, 5'd3: div_lo_sel = sample_clk_divide_i[i][1:0];
        5'd4: div_hi_en = 1'b1;
        5'd5: begin
          div_hi_en  = 1'b1;
          div_hi_sel = 1'b1;
        end
        default: div_lo_sel = 2'd2;
      endcase
    end

    prim_clkmux4 u_sample_clk_div_lo (
      .clk_i   (sample_clk_divided[i][3:0]),
      .clksel_i(div_lo_sel),
      .clk_o   (div_lo_clk[i])
    );

    prim_clock_mux2 u_sample_clk_div_hi (
      .clk0_i(sample_clk_divided[i][4]),
      .clk1_i(sample_clk_divided[i][5]),
      .sel_i (div_hi_sel),
      .clk_o (div_hi_clk[i])
    );

    prim_clock_mux2 u_sample_clk_div_mux (
      .clk0_i(div_lo_clk[i]),
      .clk1_i(div_hi_clk[i]),
      .sel_i (div_hi_en),
      .clk_o (sample_clk_o[i])
    );
  end : gen_sampler_clk

endmodule
