// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Entropy Health Tests - OpenTitan Integration
//
// This module wraps OpenTitan's division-free health test implementations:
//   - Repetition Count Test (entropy_src_repcnt_ht)
//   - Adaptive Proportion Test (entropy_src_adaptp_ht)
//   - Markov Test (entropy_src_markov_ht)
//
// Key improvements over previous implementation:
//   - NO division operations (eliminates timing violations)
//   - Window-based test synchronization
//   - Per-bit parallel testing with max/min aggregation
//
// Status bit allocation:
//   status_o[0] = Repetition Test failure
//   status_o[1] = Reserved
//   status_o[2] = Reserved
//   status_o[3] = APT Test failure (high or low threshold)
//   status_o[4] = Markov transition count too high
//   status_o[5] = Markov transition count too low
//   status_o[6] = Reserved
//   status_o[7] = Reserved
//------------------------------------------------------------------------------

module entropy_health_test #(
    parameter int unsigned DATA_WIDTH = 32  // width of entropy data input bus
) (
    input  wire logic                 clk_i,
    input  wire logic                 rst_ni,
    input  wire logic [DATA_WIDTH-1:0] entropy_i,          // entropy data stream
    input  wire logic                 entropy_valid_i,    // entropy data stream valid signal
    input  wire logic [7:0]           enable_i,           // enable bus to turn on/off various tests
    input  wire logic [7:0]           repetition_limit_i, // repetition count failure threshold
    input  wire logic [15:0]          proportion_limit_1bit_i,  // APT high count failure threshold (16-bit)
    input  wire logic [15:0]          proportion_limit_lo_i,    // APT low count failure threshold (16-bit)
    input  wire logic [9:0]           proportion_limit_2bit_i,  // Not used (OpenTitan uses hi/lo thresholds)
    input  wire logic [9:0]           proportion_limit_3bit_i,  // Not used
    input  wire logic [9:0]           proportion_limit_4bit_i,  // Not used
    // Markov test thresholds - mapped to OpenTitan's hi/lo thresholds
    input  wire logic [15:0]          markov_prob_01_threshold_i,  // High threshold (16-bit)
    input  wire logic [15:0]          markov_prob_10_threshold_i,  // Low threshold (16-bit)
    input  wire logic                 window_wrap_pulse_i,      // Window wrap pulse from window counter

    // Monitoring outputs (simplified - probability calculations removed)
    output logic [15:0]               ctr_repetition_o,
    // APT outputs - only using hi/lo counts now
    output logic [15:0]               apt_pattern_count_1bit_o,
    output logic [15:0]               apt_pattern_count_2bit_o,  // Reused for test_cnt_lo
    output logic [9:0]                apt_pattern_count_3bit_o,  // Unused
    output logic [9:0]                apt_pattern_count_4bit_o,  // Unused
    output logic [3:0]                apt_target_pattern_1bit_o,
    output logic [3:0]                apt_target_pattern_2bit_o,
    output logic [3:0]                apt_target_pattern_3bit_o,
    output logic [3:0]                apt_target_pattern_4bit_o,
    output logic [9:0]                apt_samples_processed_1bit_o,
    output logic [9:0]                apt_samples_processed_2bit_o,
    output logic [9:0]                apt_samples_processed_3bit_o,
    output logic [9:0]                apt_samples_processed_4bit_o,
    // Markov test counters - mapped from OpenTitan's hi/lo outputs
    output logic [15:0]               count_01_o,  // Reused for test_cnt_hi
    output logic [15:0]               count_10_o,  // Reused for test_cnt_lo
    output logic [15:0]               count_00_o,  // Unused (set to 0)
    output logic [15:0]               count_11_o,  // Unused (set to 0)
    output logic [7:0]                prob_01_o,   // Unused (set to 0) - no probability calculation
    output logic [7:0]                prob_10_o,   // Unused (set to 0)
    output logic [7:0]                prob_00_o,   // Unused (set to 0)
    output logic [7:0]                prob_11_o,   // Unused (set to 0)
    // Consolidated test status vector: 0=pass, 1=fail
    output logic [7:0]                status_o
);

    // OpenTitan module parameters
    localparam int unsigned RegWidth          = 16;
    localparam int unsigned RngBusWidth       = DATA_WIDTH;
    localparam int unsigned RngBusBitSelWidth = $clog2(DATA_WIDTH);

    // Internal signals
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

    // Map failure pulses to status bits
    assign status_o = {
        1'b0,                       // [7] Reserved
        1'b0,                       // [6] Reserved
        markov_test_fail_lo,        // [5] Markov transition count too low
        markov_test_fail_hi,        // [4] Markov transition count too high
        apt_test_fail_hi | apt_test_fail_lo,  // [3] APT failure (any threshold)
        1'b0,                       // [2] Reserved
        1'b0,                       // [1] Reserved
        repcnt_test_fail            // [0] Repetition test failure
    };

    // Map OpenTitan counts to legacy output ports (full 16-bit width)
    assign ctr_repetition_o             = repcnt_test_cnt;        // Full 16-bit
    assign apt_pattern_count_1bit_o     = apt_test_cnt_hi;        // Full 16-bit high count
    assign apt_pattern_count_2bit_o     = apt_test_cnt_lo;        // Full 16-bit low count
    assign apt_pattern_count_3bit_o     = 10'd0;  // Unused
    assign apt_pattern_count_4bit_o     = 10'd0;  // Unused
    assign apt_target_pattern_1bit_o    = 4'd0;   // Not applicable
    assign apt_target_pattern_2bit_o    = 4'd0;
    assign apt_target_pattern_3bit_o    = 4'd0;
    assign apt_target_pattern_4bit_o    = 4'd0;
    assign apt_samples_processed_1bit_o = 10'd0;  // Not tracked in OpenTitan version
    assign apt_samples_processed_2bit_o = 10'd0;
    assign apt_samples_processed_3bit_o = 10'd0;
    assign apt_samples_processed_4bit_o = 10'd0;

    assign count_01_o = markov_test_cnt_hi;  // High transition count
    assign count_10_o = markov_test_cnt_lo;  // Low transition count
    assign count_00_o = 16'd0;  // Not tracked by OpenTitan Markov test
    assign count_11_o = 16'd0;  // Not tracked by OpenTitan Markov test

    // Probability outputs removed (no division operations)
    assign prob_01_o = 8'd0;
    assign prob_10_o = 8'd0;
    assign prob_00_o = 8'd0;
    assign prob_11_o = 8'd0;

    // Threshold assignments: direct mapping from register values to count thresholds
    // Both 8-bit and 32-bit instances use the same threshold values
    logic [15:0] apt_thresh_hi;
    logic [15:0] apt_thresh_lo;
    logic [15:0] markov_thresh_hi;
    logic [15:0] markov_thresh_lo;

    assign apt_thresh_hi    = proportion_limit_1bit_i;  // Direct count threshold
    assign apt_thresh_lo    = proportion_limit_lo_i;   // Low threshold (detect too few 1s)
    assign markov_thresh_hi = markov_prob_01_threshold_i;  // Direct count threshold
    assign markov_thresh_lo = markov_prob_10_threshold_i;  // Low threshold

    //--------------------------------------------------------------------------
    // Repetition Count Test (OpenTitan)
    //--------------------------------------------------------------------------
    entropy_src_repcnt_ht #(
        .RegWidth          (RegWidth),
        .RngBusWidth       (RngBusWidth),
        .RngBusBitSelWidth (RngBusBitSelWidth)
    ) u_repcnt_ht (
        .clk_i             (clk_i),
        .rst_ni            (rst_ni),
        .entropy_bit_i     (entropy_i),
        .entropy_bit_vld_i (entropy_valid_i),
        .rng_bit_en_i      (1'b0),  // Test all bits in parallel
        .rng_bit_sel_i     ('0),    // Don't care when rng_bit_en_i=0
        .clear_i           (~enable_i[0]),  // Clear when disabled
        .active_i          (enable_i[0]),   // Active when enabled
        .thresh_i          ({8'd0, repetition_limit_i}),
        .test_cnt_o        (repcnt_test_cnt),
        .test_fail_pulse_o (repcnt_test_fail),
        .count_err_o       (repcnt_count_err)
    );

    //--------------------------------------------------------------------------
    // Adaptive Proportion Test (OpenTitan)
    //--------------------------------------------------------------------------
    entropy_src_adaptp_ht #(
        .RegWidth          (RegWidth),
        .RngBusWidth       (RngBusWidth),
        .RngBusBitSelWidth (RngBusBitSelWidth)
    ) u_adaptp_ht (
        .clk_i                (clk_i),
        .rst_ni               (rst_ni),
        .entropy_bit_i        (entropy_i),
        .entropy_bit_vld_i    (entropy_valid_i),
        .rng_bit_en_i         (1'b0),  // Test all bits in parallel
        .rng_bit_sel_i        ('0),    // Don't care
        .clear_i              (~enable_i[1]),  // Clear when disabled
        .active_i             (enable_i[1]),   // Active when enabled
        .thresh_hi_i          (apt_thresh_hi),
        .thresh_lo_i          (apt_thresh_lo),
        .window_wrap_pulse_i  (window_wrap_pulse_i),
        .threshold_scope_i    (1'b0),  // 0=per-bit (use max/min), 1=aggregated (use sum)
        .test_cnt_hi_o        (apt_test_cnt_hi),
        .test_cnt_lo_o        (apt_test_cnt_lo),
        .test_fail_hi_pulse_o (apt_test_fail_hi),
        .test_fail_lo_pulse_o (apt_test_fail_lo),
        .count_err_o          (apt_count_err)
    );

    //--------------------------------------------------------------------------
    // Markov Test (OpenTitan) - NO DIVISIONS!
    //--------------------------------------------------------------------------
    entropy_src_markov_ht #(
        .RegWidth          (RegWidth),
        .RngBusWidth       (RngBusWidth),
        .RngBusBitSelWidth (RngBusBitSelWidth)
    ) u_markov_ht (
        .clk_i                (clk_i),
        .rst_ni               (rst_ni),
        .entropy_bit_i        (entropy_i),
        .entropy_bit_vld_i    (entropy_valid_i),
        .rng_bit_en_i         (1'b0),  // Test all bits in parallel
        .rng_bit_sel_i        ('0),    // Don't care
        .clear_i              (~enable_i[2]),  // Clear when disabled
        .active_i             (enable_i[2]),   // Active when enabled
        .thresh_hi_i          (markov_thresh_hi),
        .thresh_lo_i          (markov_thresh_lo),
        .window_wrap_pulse_i  (window_wrap_pulse_i),
        .threshold_scope_i    (1'b0),  // 0=per-bit (use max/min)
        .test_cnt_hi_o        (markov_test_cnt_hi),
        .test_cnt_lo_o        (markov_test_cnt_lo),
        .test_fail_hi_pulse_o (markov_test_fail_hi),
        .test_fail_lo_pulse_o (markov_test_fail_lo),
        .count_err_o          (markov_count_err)
    );

endmodule
