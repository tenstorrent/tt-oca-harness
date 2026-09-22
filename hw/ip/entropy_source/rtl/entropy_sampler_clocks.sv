// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_sampler_clocks.sv
 * @brief Per-generator sample-clock multiplexer and ripple divider network.
 *
 * @details This module provides independent sample-clock selection and division
 *          for each of NRINGS noise generators. Each generator can select
 *          between an external sample clock and a shared internal ring
 *          oscillator, then further divide by factors ÷1 through ÷32 (in
 *          powers of two). The shared RO is enabled whenever ANY generator is
 *          enabled and detunes when ANY generator requests detune (OR-based
 *          aggregation). The shared RO is approximately 10× longer than the
 *          noise-generating ROs to achieve the target frequency ratio, with
 *          the detuned length chosen to preserve that ratio.
 *
 * @param NRINGS  Number of independent ring oscillators and sampler channels.
 *                 Default: 12
 */

module entropy_sampler_clocks #(
  parameter int unsigned NRINGS = 12
) (
  input       logic                   clk_i,
  input       logic                   rst_ni,
  input       logic                   sample_clk_i,
  input       logic [NRINGS-1:0]      sample_clk_select_i,
  input       logic [NRINGS-1:0]      enable_i,
  input       logic [NRINGS-1:0]      detune_ro_i,
  input       logic [NRINGS-1:0][4:0] sample_clk_divide_i,
  output      logic [NRINGS-1:0]      sample_clk_o
);

  /////////////////////
  // Local parameters
  /////////////////////

  // Shared RO: ~10× longer than noise-generating ROs to achieve the target
  // frequency ratio; detuned length chosen to preserve that ratio
  localparam int unsigned SHARED_TOTAL_LENGTH = 109;
  localparam int unsigned SHARED_TAPPED_LENGTH = 53;

  /////////////
  // Signals
  /////////////

  logic shared_ring_osc_clk;
  logic shared_detune_enable;

  logic [NRINGS-1:0]      selected_clk;
  logic [NRINGS-1:0][5:0] sample_clk_divided;
  logic [NRINGS-1:0]      div_lo_clk;
  logic [NRINGS-1:0]      div_hi_clk;

  /////////////////
  // Combinational
  /////////////////

  // Shared RO detunes if ANY generator requests it
  assign shared_detune_enable = |detune_ro_i;

  /////////////////
  // Sub-instances
  /////////////////

  entropy_ring_oscillator #(
    .TOTAL_LENGTH  (SHARED_TOTAL_LENGTH),
    .TAPPED_LENGTH (SHARED_TAPPED_LENGTH)
  ) u_shared_ro (
    .enable_i (|enable_i),
    .detune_i (shared_detune_enable),
    .noise_o  (shared_ring_osc_clk)
  );

  // Clock-cell selects are not glitch-free. sample_clk_select_i[i] and
  // sample_clk_divide_i[i] change only while enable_i[i] is low.
  for (genvar i = 0; i < NRINGS; i++) begin : gen_sampler_clk
    logic       div_hi_en;
    logic       div_hi_sel;
    logic [1:0] div_lo_sel;

    prim_clock_mux2 u_sample_clk_src_mux (
      .clk0_i(sample_clk_i),
      .clk1_i(shared_ring_osc_clk),
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
      .i_clk   (sample_clk_divided[i][3:0]),
      .i_clksel(div_lo_sel),
      .o_clk   (div_lo_clk[i])
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
