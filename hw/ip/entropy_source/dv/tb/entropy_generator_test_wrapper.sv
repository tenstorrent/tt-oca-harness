// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Generator Test Wrapper
//
// Description:
// Test wrapper for entropy_generator and entropy_sampler_clocks that exposes
// internal divided clock signals for testbench verification. This is only used
// for testing the sample clock divider functionality.
//
// The ripple dividers live in entropy_sampler_clocks, so this wrapper
// instantiates it together with entropy_generator to expose the divided
// clock signals.
//------------------------------------------------------------------------------
`timescale 1ns / 1ps

module entropy_generator_test_wrapper #(
  parameter int unsigned TOTAL_LENGTH  = 17,
  parameter int unsigned TAPPED_LENGTH = 13,
  parameter int unsigned CLKDIV_WIDTH  = 24
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    sample_clk_i,
  input  logic                    enable_i,
  input  logic [4:0]              sample_clk_divide_i,

  // Exposed outputs for testing
  output logic                    divided_clk_o,      // The selected divided clock
  output logic [5:0]              all_divided_clks_o, // All division outputs (÷1, ÷2, ÷4, ÷8, ÷16, ÷32)
  output logic                    noise_bit_o,
  output logic [7:0]              entropy_byte_o,
  output logic                    entropy_byte_valid_o
);

  // Internal signals to configure the generator
  logic                    auto_tune_enable;
  logic                    detune_ro;
  logic [CLKDIV_WIDTH-1:0] sample_clk_div;
  logic                    bypass_decorrelator;
  logic [7:0]              entropy_byte_mask;
  logic [2:0]              test_enable;
  logic [7:0]              repetition_limit;
  logic [15:0]             proportion_limit_1bit;
  logic [15:0]             proportion_limit_lo;
  logic [15:0]             markov_prob_01_threshold;
  logic [15:0]             markov_prob_10_threshold;
  logic [7:0]              test_status;

  // Default configuration for testing
  assign auto_tune_enable           = 1'b0;
  assign detune_ro                  = 1'b0;
  assign sample_clk_div             = 24'd63;  // Default decorrelator divider
  assign bypass_decorrelator        = 1'b1;    // Bypass for faster response
  assign entropy_byte_mask          = 8'hFF;
  assign test_enable                = 3'b000;  // Disable health tests for this test
  assign repetition_limit           = 8'd15;
  assign proportion_limit_1bit      = 16'd650;
  assign proportion_limit_lo        = 16'd374;
  assign markov_prob_01_threshold   = 16'd100;
  assign markov_prob_10_threshold   = 16'd100;

  // Instantiate entropy_sampler_clocks to generate divided sample clock
  // Note: Using NRINGS=1 for single generator test
  logic sample_clk_divided_out;
  entropy_sampler_clocks #(
    .NRINGS(1)
  ) u_sampler_clocks (
    .clk_i,
    .rst_ni,
    .sample_clk_i,
    .sample_clk_select_i  (1'b0),           // Use external clock (not ring osc)
    .enable_i             (enable_i),
    .detune_ro_i          (1'b0),
    .sample_clk_divide_i  (sample_clk_divide_i),
    .sample_clk_o         (sample_clk_divided_out)
  );

  // Instantiate the entropy generator (receives already-divided clock)
  entropy_generator #(
    .TOTAL_LENGTH  (TOTAL_LENGTH),
    .TAPPED_LENGTH (TAPPED_LENGTH),
    .CLKDIV_WIDTH  (CLKDIV_WIDTH)
  ) dut (
    .clk_i,
    .rst_ni,
    .sample_clk_i               (sample_clk_divided_out), // Divided clock from sampler_clocks
    .enable_i,
    .auto_tune_enable_i         (auto_tune_enable),
    .detune_ro_i                (detune_ro),
    .sample_clk_div_i           (sample_clk_div),
    .bypass_decorrelator_i      (bypass_decorrelator),
    .entropy_byte_mask_i        (entropy_byte_mask),
    .test_enable_i              (test_enable),
    .repetition_limit_i         (repetition_limit),
    .proportion_limit_1bit_i    (proportion_limit_1bit),
    .proportion_limit_lo_i      (proportion_limit_lo),
    .markov_prob_01_threshold_i (markov_prob_01_threshold),
    .markov_prob_10_threshold_i (markov_prob_10_threshold),
    .window_wrap_pulse_i        (1'b0),
    .noise_bit_monitor_o        (noise_bit_o),
    .test_status_o              (test_status),
    .entropy_byte_o             (entropy_byte_o),
    .entropy_byte_valid_o       (entropy_byte_valid_o),
    .count_err_o                ()
  );

  // Expose the internal divided clocks from entropy_sampler_clocks for testing
  // Access the first (and only) generator's divided clocks
  assign all_divided_clks_o = u_sampler_clocks.sample_clk_divided[0];
  assign divided_clk_o      = sample_clk_divided_out;

endmodule
