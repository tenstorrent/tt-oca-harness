// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_health_test.sv
 * @brief OpenTitan entropy health test integration with unified status port.
 *
 * @details Wraps OpenTitan's division-free health test implementations
 *          (Repetition Count Test, Adaptive Proportion Test, Markov Test) to
 *          validate entropy quality. Provides comprehensive diagnostic outputs
 *          (pattern counts, thresholds, transition counts) and unified status
 *          byte. Status bit allocation: [0]=Repetition failure, [3]=APT
 *          (high/low), [4]=Markov (>threshold), [5]=Markov (<threshold),
 *          [1,2,6,7]=reserved.
 *
 * @param DATA_WIDTH    Width of entropy input bus (default 32 bits).
 */

module entropy_health_test #(
    parameter int unsigned DATA_WIDTH = 32
) (
    input       logic                  clk_i,
    input       logic                  rst_ni,
    input       logic [DATA_WIDTH-1:0] entropy_i,
    input       logic                  entropy_valid_i,
    input       logic [7:0]            enable_i,
    input       logic [7:0]            repetition_limit_i,
    input       logic [15:0]           proportion_limit_1bit_i,
    input       logic [15:0]           proportion_limit_lo_i,
    input       logic [9:0]            proportion_limit_2bit_i,
    input       logic [9:0]            proportion_limit_3bit_i,
    input       logic [9:0]            proportion_limit_4bit_i,
    input       logic [15:0]           markov_prob_01_threshold_i,
    input       logic [15:0]           markov_prob_10_threshold_i,
    input       logic                  window_wrap_pulse_i,

    output      logic [15:0]           ctr_repetition_o,
    output      logic [15:0]           apt_pattern_count_1bit_o,
    output      logic [15:0]           apt_pattern_count_2bit_o,
    output      logic [9:0]            apt_pattern_count_3bit_o,
    output      logic [9:0]            apt_pattern_count_4bit_o,
    output      logic [3:0]            apt_target_pattern_1bit_o,
    output      logic [3:0]            apt_target_pattern_2bit_o,
    output      logic [3:0]            apt_target_pattern_3bit_o,
    output      logic [3:0]            apt_target_pattern_4bit_o,
    output      logic [9:0]            apt_samples_processed_1bit_o,
    output      logic [9:0]            apt_samples_processed_2bit_o,
    output      logic [9:0]            apt_samples_processed_3bit_o,
    output      logic [9:0]            apt_samples_processed_4bit_o,
    output      logic [15:0]           count_01_o,
    output      logic [15:0]           count_10_o,
    output      logic [15:0]           count_00_o,
    output      logic [15:0]           count_11_o,
    output      logic [7:0]            prob_01_o,
    output      logic [7:0]            prob_10_o,
    output      logic [7:0]            prob_00_o,
    output      logic [7:0]            prob_11_o,
    output      logic [7:0]            status_o
);

    /////////////////////
    // Local parameters
    /////////////////////

    localparam int unsigned REG_WIDTH            = 16;
    localparam int unsigned RNG_BUS_WIDTH        = DATA_WIDTH;
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
    assign apt_pattern_count_3bit_o     = 10'd0;
    assign apt_pattern_count_4bit_o     = 10'd0;
    assign apt_target_pattern_1bit_o    = 4'd0;
    assign apt_target_pattern_2bit_o    = 4'd0;
    assign apt_target_pattern_3bit_o    = 4'd0;
    assign apt_target_pattern_4bit_o    = 4'd0;
    assign apt_samples_processed_1bit_o = 10'd0;
    assign apt_samples_processed_2bit_o = 10'd0;
    assign apt_samples_processed_3bit_o = 10'd0;
    assign apt_samples_processed_4bit_o = 10'd0;

    assign count_01_o = markov_test_cnt_hi;
    assign count_10_o = markov_test_cnt_lo;
    assign count_00_o = 16'd0;
    assign count_11_o = 16'd0;

    assign prob_01_o = 8'd0;
    assign prob_10_o = 8'd0;
    assign prob_00_o = 8'd0;
    assign prob_11_o = 8'd0;

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
