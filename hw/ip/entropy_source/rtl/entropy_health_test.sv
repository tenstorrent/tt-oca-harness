// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Run OpenTitan Repetition, Adaptive Proportion, and Markov health tests with a unified status
// byte.
//
// enable_i selects which tests run; window_wrap_pulse_i closes each window. The block
// exposes raw repetition/APT/Markov counts and apt_fail_hi_o/apt_fail_lo_o pulses.
//
// status_o bits:
//
// - [0] Repetition failure
// - [3] APT high/low
// - [4] Markov above threshold
// - [5] Markov below threshold
// - [1,2,6,7] reserved
//
// count_err_o sets when a health-test counter's duplicate copies disagree (prim_count
// fault detection), independent of threshold trips; callers must route it to the alert
// path because a glitched counter can stop reporting real failures.

module entropy_health_test #(
  parameter int unsigned DATA_WIDTH = 32  // Number of parallel entropy bit streams tested, one
                                          // counter set per bit.
) (
  input       logic                  clk_i,  // System clock.
  input       logic                  rst_ni,  // Active-low reset.
  input       logic [DATA_WIDTH-1:0] entropy_i,  // Entropy word; each bit is tested as its own
                                                 // stream.
  input       logic                  entropy_valid_i,  // Qualifies entropy_i for one sample.
  input       logic [2:0]            enable_i,  // Per-test enables: bit 0 repetition, bit 1 APT,
                                                // bit 2 Markov; a clear bit holds that test's
                                                // counters cleared.
  input       logic [7:0]            repetition_limit_i,  // Repetition-count failure threshold: a
                                                          // bit repeating this many consecutive
                                                          // samples fails.
  input       logic [15:0]           proportion_limit_1bit_i,  // APT high threshold; fails when the
                                                               // largest per-bit ones count in a
                                                               // window exceeds it.
  input       logic [15:0]           proportion_limit_lo_i,  // APT low threshold; fails when the
                                                             // smallest per-bit ones count in a
                                                             // window falls below it.
  input       logic [15:0]           markov_prob_01_threshold_i,  // Markov high threshold; fails
                                                                  // when the largest per-bit 01/10
                                                                  // pair count exceeds it.
  input       logic [15:0]           markov_prob_10_threshold_i,  // Markov low threshold; fails
                                                                  // when the smallest per-bit 01/10
                                                                  // pair count falls below it.
  input       logic                  window_wrap_pulse_i,  // End-of-window strobe that evaluates
                                                           // and restarts the APT and Markov
                                                           // counts.

  output      logic [15:0]           ctr_repetition_o,  // Longest current run of identical samples
                                                        // across all bit streams.
  output      logic [15:0]           apt_pattern_count_1bit_o,  // Largest per-bit ones count in the
                                                                // current APT window.
  output      logic [15:0]           apt_pattern_count_2bit_o,  // Smallest per-bit ones count in
                                                                // the current APT window.
  output      logic [15:0]           count_01_o,  // Largest per-bit Markov 01/10 pair count in the
                                                  // current window.
  output      logic [15:0]           count_10_o,  // Smallest per-bit Markov 01/10 pair count in the
                                                  // current window.
  output      logic                  apt_fail_hi_o,  // Single-cycle pulse at a window end where the
                                                     // APT high threshold is exceeded.
  output      logic                  apt_fail_lo_o,  // Single-cycle pulse at a window end where the
                                                     // APT low threshold is undershot.
  output      logic [7:0]            status_o,  // Health-test failure pulses, encoded as listed
                                                // above.
  output      logic                  count_err_o  // Redundant-counter disagreement in any of the
                                                  // three tests.
);

  /////////////////////
  // Local parameters
  /////////////////////

  localparam int unsigned RegWidth = 16;
  localparam int unsigned RngBusWidth = DATA_WIDTH;
  localparam int unsigned RngBusBitSelWidth = $clog2(DATA_WIDTH);

  /////////////
  // Signals
  /////////////

  logic        repcnt_test_fail;
  logic        apt_test_fail_hi;
  logic        apt_test_fail_lo;
  logic        markov_test_fail_hi;
  logic        markov_test_fail_lo;

  logic [15:0] repcnt_test_cnt;
  logic [15:0] apt_test_cnt_hi;
  logic [15:0] apt_test_cnt_lo;
  logic [15:0] markov_test_cnt_hi;
  logic [15:0] markov_test_cnt_lo;

  logic        repcnt_count_err;
  logic        apt_count_err;
  logic        markov_count_err;

  logic [15:0] apt_thresh_hi;
  logic [15:0] apt_thresh_lo;
  logic [15:0] markov_thresh_hi;
  logic [15:0] markov_thresh_lo;

  /////////////////
  // Combinational
  /////////////////

  assign apt_thresh_hi    = proportion_limit_1bit_i;
  assign apt_thresh_lo    = proportion_limit_lo_i;
  assign markov_thresh_hi = markov_prob_01_threshold_i;
  assign markov_thresh_lo = markov_prob_10_threshold_i;

  ///////////
  // Output
  ///////////

  assign status_o = {
        1'b0,
        1'b0,
        markov_test_fail_lo,
        markov_test_fail_hi,
        apt_test_fail_hi | apt_test_fail_lo,
        1'b0,
        1'b0,
        repcnt_test_fail
    };

  assign ctr_repetition_o             = repcnt_test_cnt;
  assign apt_pattern_count_1bit_o     = apt_test_cnt_hi;
  assign apt_pattern_count_2bit_o     = apt_test_cnt_lo;

  assign count_01_o = markov_test_cnt_hi;
  assign count_10_o = markov_test_cnt_lo;

  assign apt_fail_hi_o = apt_test_fail_hi;
  assign apt_fail_lo_o = apt_test_fail_lo;
  assign count_err_o = repcnt_count_err | apt_count_err | markov_count_err;

  /////////////////
  // Sub-instances
  /////////////////

  entropy_src_repcnt_ht #(
    .RegWidth          (RegWidth),
    .RngBusWidth       (RngBusWidth),
    .RngBusBitSelWidth (RngBusBitSelWidth)
  ) u_repcnt_ht (
    .clk_i             (clk_i),
    .rst_ni            (rst_ni),
    .entropy_bit_i     (entropy_i),
    .entropy_bit_vld_i (entropy_valid_i),
    .rng_bit_en_i      (1'b0),  // test all bits in parallel
    .rng_bit_sel_i     ('0),
    .clear_i           (~enable_i[0]),
    .active_i          (enable_i[0]),
    .thresh_i          ({8'd0, repetition_limit_i}),
    .test_cnt_o        (repcnt_test_cnt),
    .test_fail_pulse_o (repcnt_test_fail),
    .count_err_o       (repcnt_count_err)
  );

  entropy_src_adaptp_ht #(
    .RegWidth          (RegWidth),
    .RngBusWidth       (RngBusWidth),
    .RngBusBitSelWidth (RngBusBitSelWidth)
  ) u_adaptp_ht (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .entropy_bit_i        (entropy_i),
    .entropy_bit_vld_i    (entropy_valid_i),
    .rng_bit_en_i         (1'b0),  // test all bits in parallel
    .rng_bit_sel_i        ('0),
    .clear_i              (~enable_i[1]),
    .active_i             (enable_i[1]),
    .thresh_hi_i          (apt_thresh_hi),
    .thresh_lo_i          (apt_thresh_lo),
    .window_wrap_pulse_i  (window_wrap_pulse_i),
    .threshold_scope_i    (1'b0),  // 0=per-bit max/min, 1=aggregated sum
    .test_cnt_hi_o        (apt_test_cnt_hi),
    .test_cnt_lo_o        (apt_test_cnt_lo),
    .test_fail_hi_pulse_o (apt_test_fail_hi),
    .test_fail_lo_pulse_o (apt_test_fail_lo),
    .count_err_o          (apt_count_err)
  );

  entropy_src_markov_ht #(
    .RegWidth          (RegWidth),
    .RngBusWidth       (RngBusWidth),
    .RngBusBitSelWidth (RngBusBitSelWidth)
  ) u_markov_ht (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .entropy_bit_i        (entropy_i),
    .entropy_bit_vld_i    (entropy_valid_i),
    .rng_bit_en_i         (1'b0),  // test all bits in parallel
    .rng_bit_sel_i        ('0),
    .clear_i              (~enable_i[2]),
    .active_i             (enable_i[2]),
    .thresh_hi_i          (markov_thresh_hi),
    .thresh_lo_i          (markov_thresh_lo),
    .window_wrap_pulse_i  (window_wrap_pulse_i),
    .threshold_scope_i    (1'b0),  // 0=per-bit max/min
    .test_cnt_hi_o        (markov_test_cnt_hi),
    .test_cnt_lo_o        (markov_test_cnt_lo),
    .test_fail_hi_pulse_o (markov_test_fail_hi),
    .test_fail_lo_pulse_o (markov_test_fail_lo),
    .count_err_o          (markov_count_err)
  );

endmodule
