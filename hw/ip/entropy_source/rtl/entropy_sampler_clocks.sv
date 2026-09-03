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

  for (genvar i = 0; i < NRINGS; i++) begin : gen_sampler_clk
    assign selected_clk[i] = sample_clk_select_i[i] ? shared_ring_osc_clk : sample_clk_i;

    entropy_ripple_divider #(
      .NUM_STAGES(5)
    ) u_sample_clk_divider (
      .rst_ni (rst_ni),
      .clk_i  (selected_clk[i]),
      .div_o  (sample_clk_divided[i])
    );

    always_comb begin
      unique case (sample_clk_divide_i[i])
        5'd0:    sample_clk_o[i] = sample_clk_divided[i][0];
        5'd1:    sample_clk_o[i] = sample_clk_divided[i][1];
        5'd2:    sample_clk_o[i] = sample_clk_divided[i][2];
        5'd3:    sample_clk_o[i] = sample_clk_divided[i][3];
        5'd4:    sample_clk_o[i] = sample_clk_divided[i][4];
        5'd5:    sample_clk_o[i] = sample_clk_divided[i][5];
        default: sample_clk_o[i] = sample_clk_divided[i][2];
      endcase
    end
  end : gen_sampler_clk

endmodule
