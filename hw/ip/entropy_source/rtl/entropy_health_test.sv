// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Run OpenTitan Repetition, Adaptive Proportion, and Markov health tests with a unified status byte.
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
  parameter int unsigned DATA_WIDTH = 32  // Data width.
) (
  input       logic                  clk_i,  // System clock.
  input       logic                  rst_ni,  // Active-low reset.
  input       logic [DATA_WIDTH-1:0] entropy_i,  // Entropy.
  input       logic                  entropy_valid_i,  // Entropy valid.
  input       logic [2:0]            enable_i,  // Block enable.
  input       logic [7:0]            repetition_limit_i,  // Repetition limit.
  input       logic [15:0]           proportion_limit_1bit_i,  // Proportion limit 1bit.
  input       logic [15:0]           proportion_limit_lo_i,  // Proportion limit lo.
  input       logic [15:0]           markov_prob_01_threshold_i,  // Markov prob 01 threshold.
  input       logic [15:0]           markov_prob_10_threshold_i,  // Markov prob 10 threshold.
  input       logic                  window_wrap_pulse_i,  // Window wrap pulse.

  output      logic [15:0]           ctr_repetition_o,  // Ctr repetition.
  output      logic [15:0]           apt_pattern_count_1bit_o,  // Apt pattern count 1bit.
  output      logic [15:0]           apt_pattern_count_2bit_o,  // Apt pattern count 2bit.
  output      logic [15:0]           count_01_o,  // Count 01.
  output      logic [15:0]           count_10_o,  // Count 10.
  output      logic                  apt_fail_hi_o,  // Apt fail hi.
  output      logic                  apt_fail_lo_o,  // Apt fail lo.
  output      logic [7:0]            status_o,  // Status.
  output      logic                  count_err_o  // Count err.
);

  /////////////////////
  // Local parameters
  /////////////////////

  localparam int unsigned REG_WIDTH = 16;
  localparam int unsigned RNG_BUS_WIDTH = DATA_WIDTH;
  localparam int unsigned RNG_BUS_BIT_SEL_WIDTH = $clog2(DATA_WIDTH);

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
    .RegWidth          (REG_WIDTH),
    .RngBusWidth       (RNG_BUS_WIDTH),
    .RngBusBitSelWidth (RNG_BUS_BIT_SEL_WIDTH)
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
    .RegWidth          (REG_WIDTH),
    .RngBusWidth       (RNG_BUS_WIDTH),
    .RngBusBitSelWidth (RNG_BUS_BIT_SEL_WIDTH)
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
    .RegWidth          (REG_WIDTH),
    .RngBusWidth       (RNG_BUS_WIDTH),
    .RngBusBitSelWidth (RNG_BUS_BIT_SEL_WIDTH)
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
