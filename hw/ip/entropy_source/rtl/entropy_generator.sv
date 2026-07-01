// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Noise Source
//
// Description:
// The entropy noise source is connected with the decorrelator to produce a
// downsampled byte stream.
//------------------------------------------------------------------------------


module entropy_generator #(
    parameter int unsigned TOTAL_LENGTH  = 17,
    parameter int unsigned TAPPED_LENGTH = 13,
    parameter int unsigned CLKDIV_WIDTH  = 24
) (
    input  logic                    clk_i,
    input  logic                    rst_ni,

    // noise sampler clock (already divided by entropy_sampler_clocks)
    input  logic                    sample_clk_i,

    // ring oscillator noise generator configuration
    input  logic                    enable_i,
    input  logic                    auto_tune_enable_i,
    input  logic                    detune_ro_i,
    input  logic [CLKDIV_WIDTH-1:0] sample_clk_div_i,

    // serial decorrelator configuration
    input  logic                    bypass_decorrelator_i,
    input  logic [7:0]              entropy_byte_mask_i,

    // health tester configurations
    input  logic [7:0]              test_enable_i,
    input  logic [7:0]              repetition_limit_i,
    input  logic [15:0]             proportion_limit_1bit_i,
    input  logic [15:0]             proportion_limit_lo_i,
    input  logic [9:0]              proportion_limit_2bit_i,
    input  logic [9:0]              proportion_limit_3bit_i,
    input  logic [9:0]              proportion_limit_4bit_i,
    input  logic [15:0]             markov_prob_01_threshold_i,
    input  logic [15:0]             markov_prob_10_threshold_i,
    input  wire logic               window_wrap_pulse_i,  // Window wrap pulse for health tests

    output logic                    noise_bit_monitor_o,
    output logic [7:0]              test_status_o,
    output logic [7:0]              entropy_byte_o,
    output logic                    entropy_byte_valid_o
);

    logic noise_bit;
    logic test_fail;
    logic auto_tune_state;

    logic detune;
    assign detune = auto_tune_enable_i ? auto_tune_state : detune_ro_i;

    // Open signals for unused health test outputs (to avoid PINCONNECTEMPTY warnings)
    logic [15:0] open_ctr_repetition;
    logic [15:0] open_apt_pattern_count_1bit, open_apt_pattern_count_2bit;
    logic [9:0]  open_apt_pattern_count_3bit, open_apt_pattern_count_4bit;
    logic [3:0]  open_apt_target_pattern_1bit, open_apt_target_pattern_2bit, open_apt_target_pattern_3bit, open_apt_target_pattern_4bit;
    logic [9:0]  open_apt_samples_processed_1bit, open_apt_samples_processed_2bit, open_apt_samples_processed_3bit, open_apt_samples_processed_4bit;
    logic [15:0] open_count_01, open_count_10, open_count_00, open_count_11;
    logic [7:0]  open_prob_01, open_prob_10, open_prob_00, open_prob_11;

    entropy_noise_source #(
        .TOTAL_LENGTH  (TOTAL_LENGTH),
        .TAPPED_LENGTH (TAPPED_LENGTH)
    ) nsrc (
        .clk_i,
        .rst_ni,
        .sample_clk_i  (sample_clk_i), // Already divided by entropy_sampler_clocks
        .enable_i      (enable_i),
        .detune_i      (detune),
        .noise_o       (noise_bit)
    );

    assign noise_bit_monitor_o = noise_bit;

    entropy_decorrelator #(
        .LENGTH                (29),
        .CLKDIV_WIDTH          (CLKDIV_WIDTH),
        .LFSR_MODE             (1'b0) //TODO: future feature
    ) dcor (
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
        .DATA_WIDTH                   (8)
    ) htst (
        .clk_i,
        .rst_ni,
        .entropy_i                    (entropy_byte_o),
        .entropy_valid_i              (entropy_byte_valid_o),
        .enable_i                     (test_enable_i),
        .repetition_limit_i,
        .proportion_limit_1bit_i,
        .proportion_limit_lo_i,
        .proportion_limit_2bit_i,
        .proportion_limit_3bit_i,
        .proportion_limit_4bit_i,
        .markov_prob_01_threshold_i,
        .markov_prob_10_threshold_i,
        .window_wrap_pulse_i,
        // Health test monitoring outputs (currently unused, connected to open signals)
        .ctr_repetition_o             (open_ctr_repetition),
        // APT outputs for all 4 sample sizes
        .apt_pattern_count_1bit_o     (open_apt_pattern_count_1bit),
        .apt_pattern_count_2bit_o     (open_apt_pattern_count_2bit),
        .apt_pattern_count_3bit_o     (open_apt_pattern_count_3bit),
        .apt_pattern_count_4bit_o     (open_apt_pattern_count_4bit),
        .apt_target_pattern_1bit_o    (open_apt_target_pattern_1bit),
        .apt_target_pattern_2bit_o    (open_apt_target_pattern_2bit),
        .apt_target_pattern_3bit_o    (open_apt_target_pattern_3bit),
        .apt_target_pattern_4bit_o    (open_apt_target_pattern_4bit),
        .apt_samples_processed_1bit_o (open_apt_samples_processed_1bit),
        .apt_samples_processed_2bit_o (open_apt_samples_processed_2bit),
        .apt_samples_processed_3bit_o (open_apt_samples_processed_3bit),
        .apt_samples_processed_4bit_o (open_apt_samples_processed_4bit),
        // Markov test outputs
        .count_01_o                   (open_count_01),
        .count_10_o                   (open_count_10),
        .count_00_o                   (open_count_00),
        .count_11_o                   (open_count_11),
        .prob_01_o                    (open_prob_01),
        .prob_10_o                    (open_prob_10),
        .prob_00_o                    (open_prob_00),
        .prob_11_o                    (open_prob_11),
        // report consolidated test status vector: 0=pass, 1=fail
        .status_o                     (test_status_o) // {Markov[3:0], APT, RSV[1:0], repetition}
    );

    // Generate test failure signal as OR of all status bits
    assign test_fail = |test_status_o;

    // feedback online health test status to noise ring oscillator tuning
    entropy_rosc_tune_fsm tuner (
        .clk_i,
        .rst_ni,
        .health_error_i (test_fail),
        .tune_state_o   (auto_tune_state)
    );

endmodule
