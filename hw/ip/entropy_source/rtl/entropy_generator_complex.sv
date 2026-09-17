// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_generator_complex.sv
 * @brief Multi-ring entropy generator with GF(2^8) output extraction.
 *
 * @details Instantiates NRINGS entropy generators (each with noise source,
 *          decorrelator, per-lane health test, and auto-tune FSM) and combines
 *          their byte outputs through a BIW (Between 1 and 8 Worth) GF(2^8)
 *          extractor to produce a single 32-bit entropy output stream. Hosts
 *          the shared window counter and synchronisation pulse that drives
 *          all per-lane health test window resets, enabling coordinated
 *          Repetition/APT/Markov test windows across all rings.
 *
 * @param NRINGS        Number of ring oscillator lanes (default 12).
 * @param CLKDIV_WIDTH  Width of decorrelator clock divider value (default 24).
 */

module entropy_generator_complex #(
  parameter int unsigned NRINGS       = 12,
  parameter int unsigned CLKDIV_WIDTH = 24
) (
  input       logic                    clk_i,
  input       logic                    rst_ni,
  input       logic                    sample_clk_i,
  output      logic [31:0]             entropy_stream_o,
  output      logic [NRINGS-1:0][7:0]  entropy_stream_uncompressed_o,
  output      logic                    entropy_stream_valid_o,
  output      logic [NRINGS-1:0]       noise_bit_monitor_o,
  output      logic [NRINGS-1:0]       sample_clk_monitor_o,

  output      logic [7:0]              generator_0_test_status_o,
  output      logic [7:0]              generator_1_test_status_o,
  output      logic [7:0]              generator_2_test_status_o,
  output      logic [7:0]              generator_3_test_status_o,
  output      logic [7:0]              generator_4_test_status_o,
  output      logic [7:0]              generator_5_test_status_o,
  output      logic [7:0]              generator_6_test_status_o,
  output      logic [7:0]              generator_7_test_status_o,
  output      logic [7:0]              generator_8_test_status_o,
  output      logic [7:0]              generator_9_test_status_o,
  output      logic [7:0]              generator_10_test_status_o,
  output      logic [7:0]              generator_11_test_status_o,

  // OR of every per-lane health-test counter-disagreement error and the
  // shared window counter's own; see entropy_health_test.count_err_o.
  output      logic                    count_err_o,

  input       logic [NRINGS-1:0]       jitter_ro_enable_i,
  input       logic [NRINGS-1:0]       jitter_ro_detune_i,
  input       logic [NRINGS-1:0]       jitter_ro_auto_tune_enable_i,

  input       logic [NRINGS-1:0]       sample_clk_select_i,
  input       logic [NRINGS-1:0]       sample_clk_ro_detune_i,
  input       logic [NRINGS-1:0]       sample_clk_enable_i,
  input       logic [NRINGS-1:0][4:0]  sample_clk_divide_i,

  input       logic [NRINGS-1:0]       decorrelator_bypass_i,
  input       logic [CLKDIV_WIDTH-1:0] decorrelator_sample_clk_div_i,
  input       logic [7:0]              decorrelator_entropy_byte_mask_i,

  // Master enable: window counter runs even when individual health tests
  // are disabled so the main_sm boot gate can complete its boot window.
  input       logic                    module_enable_i,

  input       logic [2:0]              health_test_enable_i,
  input       logic [7:0]              health_test_repetition_limit_i,
  input       logic [15:0]             health_test_proportion_limit_1bit_i,
  input       logic [15:0]             health_test_proportion_limit_lo_i,
  input       logic [15:0]             health_test_markov_prob_01_threshold_i,
  input       logic [15:0]             health_test_markov_prob_10_threshold_i,
  input       logic [15:0]             health_test_window_size_i,

  output      logic                    window_wrap_pulse_o
);

  /////////////////////
  // Local parameters
  /////////////////////

  // Ring oscillator lengths (simulation-friendly primes for mixed-frequency entropy)
  localparam int unsigned TOTAL_LENGTH_0 = 5, TOTAL_LENGTH_1 = 7;
  localparam int unsigned TOTAL_LENGTH_2 = 11, TOTAL_LENGTH_3 = 13;
  localparam int unsigned TOTAL_LENGTH_4 = 17, TOTAL_LENGTH_5 = 19;
  localparam int unsigned TOTAL_LENGTH_6 = 6, TOTAL_LENGTH_7 = 8;
  localparam int unsigned TOTAL_LENGTH_8 = 12, TOTAL_LENGTH_9 = 15;
  localparam int unsigned TOTAL_LENGTH_10 = 18, TOTAL_LENGTH_11 = 23;

  // Detuned lengths (shorter → higher frequency)
  localparam int unsigned TAPPED_LENGTH_0 = 3, TAPPED_LENGTH_1 = 5;
  localparam int unsigned TAPPED_LENGTH_2 = 9, TAPPED_LENGTH_3 = 10;
  localparam int unsigned TAPPED_LENGTH_4 = 14, TAPPED_LENGTH_5 = 16;
  localparam int unsigned TAPPED_LENGTH_6 = 4, TAPPED_LENGTH_7 = 7;
  localparam int unsigned TAPPED_LENGTH_8 = 11, TAPPED_LENGTH_9 = 13;
  localparam int unsigned TAPPED_LENGTH_10 = 15, TAPPED_LENGTH_11 = 21;

  //////////
  // Types
  //////////

  // Lookup functions used to parameterise the generate loop below
  function automatic int get_total_length(input int idx);
    unique case (idx)
      0:       return TOTAL_LENGTH_0;
      1:       return TOTAL_LENGTH_1;
      2:       return TOTAL_LENGTH_2;
      3:       return TOTAL_LENGTH_3;
      4:       return TOTAL_LENGTH_4;
      5:       return TOTAL_LENGTH_5;
      6:       return TOTAL_LENGTH_6;
      7:       return TOTAL_LENGTH_7;
      8:       return TOTAL_LENGTH_8;
      9:       return TOTAL_LENGTH_9;
      10:      return TOTAL_LENGTH_10;
      11:      return TOTAL_LENGTH_11;
      default: return 29;
    endcase
  endfunction

  function automatic int get_tapped_length(input int idx);
    unique case (idx)
      0:       return TAPPED_LENGTH_0;
      1:       return TAPPED_LENGTH_1;
      2:       return TAPPED_LENGTH_2;
      3:       return TAPPED_LENGTH_3;
      4:       return TAPPED_LENGTH_4;
      5:       return TAPPED_LENGTH_5;
      6:       return TAPPED_LENGTH_6;
      7:       return TAPPED_LENGTH_7;
      8:       return TAPPED_LENGTH_8;
      9:       return TAPPED_LENGTH_9;
      10:      return TAPPED_LENGTH_10;
      11:      return TAPPED_LENGTH_11;
      default: return 19;
    endcase
  endfunction

  /////////////
  // Signals
  /////////////

  logic [NRINGS-1:0]      entropy_byte_valid;
  logic [NRINGS-1:0][7:0] decorrelator_entropy_bytes;
  logic [NRINGS-1:0]      sample_clk;
  logic [7:0]             test_status [NRINGS];

  logic [15:0] window_cntr;
  logic        window_cntr_err;
  logic        window_wrap_pulse;
  logic        health_test_enable;

  logic [NRINGS-1:0] generator_count_err;

  logic [7:0] biw_entropy [4];
  logic [31:0] biw_data;
  logic        biw_valid;

  /////////////////
  // Combinational
  /////////////////

  assign health_test_enable = |health_test_enable_i;
  assign window_wrap_pulse  = (window_cntr >= health_test_window_size_i);
  assign window_wrap_pulse_o = window_wrap_pulse;

  assign entropy_stream_uncompressed_o = decorrelator_entropy_bytes;
  assign sample_clk_monitor_o          = sample_clk;

  assign generator_0_test_status_o  = test_status[0];
  assign generator_1_test_status_o  = test_status[1];
  assign generator_2_test_status_o  = test_status[2];
  assign generator_3_test_status_o  = test_status[3];
  assign generator_4_test_status_o  = test_status[4];
  assign generator_5_test_status_o  = test_status[5];
  assign generator_6_test_status_o  = test_status[6];
  assign generator_7_test_status_o  = test_status[7];
  assign generator_8_test_status_o  = test_status[8];
  assign generator_9_test_status_o  = test_status[9];
  assign generator_10_test_status_o = test_status[10];
  assign generator_11_test_status_o = test_status[11];

  assign biw_data  = {biw_entropy[0], biw_entropy[1], biw_entropy[2], biw_entropy[3]};
  assign biw_valid = |entropy_byte_valid;

  assign count_err_o = window_cntr_err | (|generator_count_err);

  assign entropy_stream_o       = biw_data;
  assign entropy_stream_valid_o = biw_valid;

  /////////////////
  // Sub-instances
  /////////////////

  entropy_sampler_clocks #(
    .NRINGS(NRINGS)
  ) u_sampler_clocks (
    .clk_i,
    .rst_ni,
    .sample_clk_i        (sample_clk_i),
    .enable_i            (sample_clk_enable_i),
    .detune_ro_i         (sample_clk_ro_detune_i),
    .sample_clk_select_i (sample_clk_select_i),
    .sample_clk_divide_i (sample_clk_divide_i),
    .sample_clk_o        (sample_clk)
  );

  // Shared window counter for health-test synchronisation (prim_count from OpenTitan)
  prim_count #(
    .Width(16)
  ) u_window_cntr (
    .clk_i             (clk_i),
    .rst_ni            (rst_ni),
    // Run whenever module or any health test is enabled; clr halts the counter
    .clr_i             (~(module_enable_i | health_test_enable)),
    .set_i             (window_wrap_pulse),
    .set_cnt_i         (16'h0),
    .incr_en_i         (|entropy_byte_valid),
    .decr_en_i         (1'b0),
    .step_i            (16'd1),
    .commit_i          (1'b1),
    .cnt_o             (window_cntr),
    .cnt_after_commit_o(),
    .err_o             (window_cntr_err)
  );

  // Per-lane generator: noise source + decorrelator + per-lane health test
  for (genvar i = 0; i < NRINGS; i++) begin : gen_ecmplx
    entropy_generator #(
      .TOTAL_LENGTH  (get_total_length (i)),
      .TAPPED_LENGTH (get_tapped_length(i)),
      .CLKDIV_WIDTH  (CLKDIV_WIDTH)
    ) u_generator (
      .clk_i,
      .rst_ni,
      .enable_i                   (jitter_ro_enable_i           [i]),
      .auto_tune_enable_i         (jitter_ro_auto_tune_enable_i [i]),
      .detune_ro_i                (jitter_ro_detune_i           [i]),
      .sample_clk_i               (sample_clk                   [i]),
      .sample_clk_div_i           (decorrelator_sample_clk_div_i),
      .bypass_decorrelator_i      (decorrelator_bypass_i        [i]),
      .entropy_byte_mask_i        (decorrelator_entropy_byte_mask_i),
      .test_enable_i              (health_test_enable_i),
      .repetition_limit_i         (health_test_repetition_limit_i),
      .proportion_limit_1bit_i    (health_test_proportion_limit_1bit_i),
      .proportion_limit_lo_i      (health_test_proportion_limit_lo_i),
      .markov_prob_01_threshold_i (health_test_markov_prob_01_threshold_i),
      .markov_prob_10_threshold_i (health_test_markov_prob_10_threshold_i),
      .window_wrap_pulse_i        (window_wrap_pulse),
      .noise_bit_monitor_o        (noise_bit_monitor_o          [i]),
      .test_status_o              (test_status                  [i]),
      .entropy_byte_o             (decorrelator_entropy_bytes   [i]),
      .entropy_byte_valid_o       (entropy_byte_valid           [i]),
      .count_err_o                (generator_count_err          [i])
    );
  end : gen_ecmplx

  // BIW GF(2^8) extractor: combines 3 groups of 4 lanes into 4 output bytes
  for (genvar i = 0; i < 4; i++) begin : gen_biw
    gf_muladd u_muladd (
      .a_i (decorrelator_entropy_bytes[i]),
      .b_i (decorrelator_entropy_bytes[i+4]),
      .c_i (decorrelator_entropy_bytes[i+8]),
      .y_o (biw_entropy               [i])
    );
  end : gen_biw

endmodule
