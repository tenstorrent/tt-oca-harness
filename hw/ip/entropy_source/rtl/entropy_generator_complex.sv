// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Combine NRINGS entropy generators through a GF(2^8) BIW extractor into one 32-bit stream.
//
// Each lane has a noise source, decorrelator, per-lane health test, and auto-tune FSM.
// Per-lane jitter_ro_*, sample_clk_*, and decorrelator_* inputs configure each generator;
// health_test_* inputs are shared.
//
// The block hosts the shared window counter and window_wrap_pulse_o, which resets all
// per-lane health-test windows together. module_enable_i keeps the window counter running
// even when individual health tests are disabled so the main_sm boot gate can finish its
// boot window.
//
// count_err_o ORs every per-lane health-test counter disagreement with the shared window
// counter's own fault.

module entropy_generator_complex #(
  parameter int unsigned NRINGS       = 12,  // Ring-oscillator lane count.
  parameter int unsigned CLKDIV_WIDTH = 24  // Downsample divider counter width.
) (
  input       logic                    clk_i,  // System clock.
  input       logic                    rst_ni,  // Active-low reset.
  input       logic                    sample_clk_i,  // Ring-oscillator sample clock.
  output      logic [31:0]             entropy_stream_o,  // Entropy stream.
  output      logic [NRINGS-1:0][7:0]  entropy_stream_uncompressed_o,  // Entropy stream uncompressed.
  output      logic                    entropy_stream_valid_o,  // Entropy stream valid.
  output      logic [NRINGS-1:0]       noise_bit_monitor_o,  // Noise bit monitor.
  output      logic [NRINGS-1:0]       sample_clk_monitor_o,  // Sample clk monitor.

  output      logic [7:0]              generator_0_test_status_o,  // Generator 0 test status.
  output      logic [7:0]              generator_1_test_status_o,  // Generator 1 test status.
  output      logic [7:0]              generator_2_test_status_o,  // Generator 2 test status.
  output      logic [7:0]              generator_3_test_status_o,  // Generator 3 test status.
  output      logic [7:0]              generator_4_test_status_o,  // Generator 4 test status.
  output      logic [7:0]              generator_5_test_status_o,  // Generator 5 test status.
  output      logic [7:0]              generator_6_test_status_o,  // Generator 6 test status.
  output      logic [7:0]              generator_7_test_status_o,  // Generator 7 test status.
  output      logic [7:0]              generator_8_test_status_o,  // Generator 8 test status.
  output      logic [7:0]              generator_9_test_status_o,  // Generator 9 test status.
  output      logic [7:0]              generator_10_test_status_o,  // Generator 10 test status.
  output      logic [7:0]              generator_11_test_status_o,  // Generator 11 test status.

  output      logic                    count_err_o,  // Count err.

  input       logic [NRINGS-1:0]       jitter_ro_enable_i,  // Jitter ro enable.
  input       logic [NRINGS-1:0]       jitter_ro_detune_i,  // Jitter ro detune.
  input       logic [NRINGS-1:0]       jitter_ro_auto_tune_enable_i,  // Jitter ro auto tune enable.

  input       logic [NRINGS-1:0]       sample_clk_select_i,  // Sample clk select.
  input       logic [NRINGS-1:0]       sample_clk_ro_detune_i,  // Sample clk ro detune.
  input       logic [NRINGS-1:0]       sample_clk_enable_i,  // Sample clk enable.
  input       logic [NRINGS-1:0][4:0]  sample_clk_divide_i,  // Sample clk divide.

  input       logic [NRINGS-1:0]       decorrelator_bypass_i,  // Decorrelator bypass.
  input       logic [CLKDIV_WIDTH-1:0] decorrelator_sample_clk_div_i,  // Decorrelator sample clk div.
  input       logic [7:0]              decorrelator_entropy_byte_mask_i,  // Decorrelator entropy byte mask.

  input       logic                    module_enable_i,  // Module enable.

  input       logic [2:0]              health_test_enable_i,  // Health test enable.
  input       logic [7:0]              health_test_repetition_limit_i,  // Health test repetition limit.
  input       logic [15:0]             health_test_proportion_limit_1bit_i,  // Health test proportion limit 1bit.
  input       logic [15:0]             health_test_proportion_limit_lo_i,  // Health test proportion limit lo.
  input       logic [15:0]             health_test_markov_prob_01_threshold_i,  // Health test markov prob 01 threshold.
  input       logic [15:0]             health_test_markov_prob_10_threshold_i,  // Health test markov prob 10 threshold.
  input       logic [15:0]             health_test_window_size_i,  // Health test window size.

  output      logic                    window_wrap_pulse_o  // Window wrap pulse.
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
