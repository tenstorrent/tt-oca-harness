// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_generator.sv
 * @brief Single-lane entropy generator with noise source, decorrelator, and
 *        auto-tune control.
 *
 * @details Combines one entropy noise source (ring oscillator sampled by slower
 *          clock) with its decorrelator (LFSR-based whitener), per-lane health
 *          test (Repetition/APT/Markov), and auto-tune FSM. The auto-tune FSM
 *          adaptively adjusts ring oscillator detuning based on test results
 *          to maintain entropy quality. Intended to be instantiated once per
 *          ring oscillator lane inside entropy_generator_complex, with each
 *          lane producing an 8-bit entropy byte.
 *
 * @param TOTAL_LENGTH   Full ring oscillator length (default 17 stages).
 * @param TAPPED_LENGTH  Detuned tap point length; shorter yields higher
 *                       frequency (default 13 stages).
 * @param CLKDIV_WIDTH   Width of decorrelator clock divider (default 24).
 */

module entropy_generator #(
  parameter int unsigned TOTAL_LENGTH  = 17,
  parameter int unsigned TAPPED_LENGTH = 13,
  parameter int unsigned CLKDIV_WIDTH  = 24
) (
  input       logic                    clk_i,
  input       logic                    rst_ni,

  input       logic                    sample_clk_i,

  input       logic                    enable_i,
  input       logic                    auto_tune_enable_i,
  input       logic                    detune_ro_i,
  input       logic [CLKDIV_WIDTH-1:0] sample_clk_div_i,

  input       logic                    bypass_decorrelator_i,
  input       logic [7:0]              entropy_byte_mask_i,

  input       logic [2:0]              test_enable_i,
  input       logic [7:0]              repetition_limit_i,
  input       logic [15:0]             proportion_limit_1bit_i,
  input       logic [15:0]             proportion_limit_lo_i,
  input       logic [15:0]             markov_prob_01_threshold_i,
  input       logic [15:0]             markov_prob_10_threshold_i,
  input       logic                    window_wrap_pulse_i,

  output      logic                    noise_bit_monitor_o,
  output      logic [7:0]              test_status_o,
  output      logic [7:0]              entropy_byte_o,
  output      logic                    entropy_byte_valid_o,
  // This lane's health-test counter-disagreement error; see entropy_health_test.
  output      logic                    count_err_o
);

  /////////////
  // Signals
  /////////////

  logic noise_bit;
  logic test_fail;
  logic auto_tune_state;
  logic detune;

  // Tie-offs for health-test monitoring outputs not used at this level
  logic [15:0] open_ctr_repetition;
  logic [15:0] open_apt_pattern_count_1bit, open_apt_pattern_count_2bit;
  logic [15:0] open_count_01, open_count_10;

  /////////////////
  // Combinational
  /////////////////

  assign detune           = auto_tune_enable_i ? auto_tune_state : detune_ro_i;
  assign noise_bit_monitor_o = noise_bit;
  assign test_fail        = |test_status_o;

  /////////////////
  // Sub-instances
  /////////////////

  entropy_noise_source #(
    .TOTAL_LENGTH  (TOTAL_LENGTH),
    .TAPPED_LENGTH (TAPPED_LENGTH)
  ) u_noise_source (
    .clk_i,
    .rst_ni,
    .sample_clk_i (sample_clk_i),
    .enable_i     (enable_i),
    .detune_i     (detune),
    .noise_o      (noise_bit)
  );

  entropy_decorrelator #(
    .LENGTH       (29),
    .CLKDIV_WIDTH (CLKDIV_WIDTH),
    .LFSR_MODE    (1'b0)
  ) u_decorrelator (
    .clk_i,
    .rst_ni,
    .enable_i,
    .noise_i               (noise_bit),
    .bypass_i              (bypass_decorrelator_i),
    .byte_mask_i           (entropy_byte_mask_i),
    .sample_clk_div_i,
    .entropy_byte_sample_o (entropy_byte_o),
    .entropy_byte_valid_o
  );

  entropy_health_test #(
    .DATA_WIDTH(8)
  ) u_health_test (
    .clk_i,
    .rst_ni,
    .entropy_i                    (entropy_byte_o),
    .entropy_valid_i              (entropy_byte_valid_o),
    .enable_i                     (test_enable_i),
    .repetition_limit_i,
    .proportion_limit_1bit_i,
    .proportion_limit_lo_i,
    .markov_prob_01_threshold_i,
    .markov_prob_10_threshold_i,
    .window_wrap_pulse_i,
    .ctr_repetition_o             (open_ctr_repetition),
    .apt_pattern_count_1bit_o     (open_apt_pattern_count_1bit),
    .apt_pattern_count_2bit_o     (open_apt_pattern_count_2bit),
    .count_01_o                   (open_count_01),
    .count_10_o                   (open_count_10),
    .apt_fail_hi_o                (),
    .apt_fail_lo_o                (),
    .status_o                     (test_status_o),
    .count_err_o                  (count_err_o)
  );

  entropy_rosc_tune_fsm u_tune_fsm (
    .clk_i,
    .rst_ni,
    .health_error_i (test_fail),
    .tune_state_o   (auto_tune_state)
  );

endmodule
