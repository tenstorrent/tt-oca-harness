// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Generate one entropy lane from a noise source, decorrelator, health tests, and auto-tune.
//
// Combines a TOTAL_LENGTH/TAPPED_LENGTH ring oscillator sampled on sample_clk_i with
// decorrelation and Repetition/APT/Markov tests.
//
// Controls:
//
// - auto_tune_enable_i lets health failures retune detune through the tune FSM;
//   detune_ro_i forces detune.
// - bypass_decorrelator_i and entropy_byte_mask_i configure the decorrelator;
//   sample_clk_div_i sets its downsample.
// - test_enable_i and the limit/threshold inputs program the three health tests;
//   window_wrap_pulse_i closes each window.
//
// count_err_o is this lane's health-test counter-disagreement error.

module entropy_generator #(
  parameter int unsigned TOTAL_LENGTH  = 17,  // Full ring-oscillator stage count.
  parameter int unsigned TAPPED_LENGTH = 13,  // Stage count of the shorter feedback tap, used while
                                              // detune is low.
  parameter int unsigned CLKDIV_WIDTH  = 24  // Downsample divider counter width.
) (
  input       logic                    clk_i,  // System clock.
  input       logic                    rst_ni,  // Active-low asynchronous reset.

  input       logic                    sample_clk_i,  // Ring-oscillator sample clock.

  input       logic                    enable_i,  // Enables the noise ring oscillator and the
                                                  // decorrelator.
  input       logic                    auto_tune_enable_i,  // High lets the tune FSM drive the ring
                                                            // detune in place of detune_ro_i.
  input       logic                    detune_ro_i,  // Manual ring detune while auto-tune is off:
                                                     // high selects the full TOTAL_LENGTH feedback
                                                     // path, low the shorter tap.
  input       logic [CLKDIV_WIDTH-1:0] sample_clk_div_i,  // Decorrelator downsample period minus
                                                          // one, in clk_i cycles.

  input       logic                    bypass_decorrelator_i,  // High removes the decorrelator XOR
                                                               // feedback.
  input       logic [7:0]              entropy_byte_mask_i,  // AND mask on each decorrelator output
                                                             // byte.

  input       logic [2:0]              test_enable_i,  // Health-test enables: bit 0 repetition, bit
                                                       // 1 APT, bit 2 Markov.
  input       logic [7:0]              repetition_limit_i,  // Repetition-count failure threshold.
  input       logic [15:0]             proportion_limit_1bit_i,  // APT high threshold on the
                                                                 // per-bit ones count per window.
  input       logic [15:0]             proportion_limit_lo_i,  // APT low threshold on the per-bit
                                                               // ones count per window.
  input       logic [15:0]             markov_prob_01_threshold_i,  // Markov high threshold on the per-bit 01/10
                                                                    // pair count per window.
  input       logic [15:0]             markov_prob_10_threshold_i,  // Markov low threshold on the per-bit 01/10
                                                                    // pair count per window.
  input       logic                    window_wrap_pulse_i,  // Shared end-of-window strobe that
                                                             // evaluates and restarts the APT and
                                                             // Markov tests.

  output      logic                    noise_bit_monitor_o,  // Synchronized noise-source bit, for
                                                             // debug observation.
  output      logic [7:0]              test_status_o,  // Health-test status byte, encoded as
                                                       // entropy_health_test status_o.
  output      logic [7:0]              entropy_byte_o,  // Masked decorrelator output byte.
  output      logic                    entropy_byte_valid_o,  // Single-cycle strobe marking a new
                                                              // entropy_byte_o.
  output      logic                    count_err_o  // Redundant-counter fault in this lane's health
                                                    // tests.
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
