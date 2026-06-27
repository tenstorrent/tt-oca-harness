// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

`timescale 1ns/1ps

interface ro_cfg_if #(
  parameter int N = 16,
  parameter int PROB_SCALE = 1_000_000
);
  // Global enables
  logic              enable;
  logic              seed_en;
  // Per-RO configuration arrays
  logic [31:0]       seed      [N]; // 32-bit unsigned seed
  int unsigned       p_bias    [N]; // 0..PROB_SCALE
  int unsigned       p_corr    [N]; // 0..PROB_SCALE
  logic              stuck_en  [N];
  logic              stuck_val [N];

  // 32-bit word generation mode (health test direct injection)
  logic              word32_enable;        // Enable 32-bit word generation
  int unsigned       word32_p_bias;        // Bias for 32-bit word generation
  int unsigned       word32_p_corr;        // Correlation for 32-bit word generation
  logic              word32_use_fixed;     // Use fixed value (not probabilistic)
  logic [31:0]       word32_fixed_value;   // Fixed 32-bit value to inject
  logic [31:0]       word32_data;          // Generated 32-bit word (from random or fixed)
  logic              word32_valid;         // Word valid signal

  // Power-on defaults to avoid X propagation before Python configuration
  // NOTE: All runtime defaults are specified and applied in test_config.py (ROConfig)
  //       via ro_init() function in test_base.py
  // These are minimal fallbacks only to prevent X propagation
  initial begin
    int i;
    enable  = 1'b0;  // Disabled until configured by Python
    seed_en = 1'b0;
    for (i = 0; i < N; i++) begin
      seed[i]      = i + 32'h100;
      p_bias[i]    = PROB_SCALE/2;
      p_corr[i]    = PROB_SCALE/2;
      stuck_en[i]  = 1'b0;
      stuck_val[i] = 1'b0;
    end
    // Initialize word32 mode signals
    word32_enable = 1'b0;
    word32_p_bias = PROB_SCALE/2;
    word32_p_corr = PROB_SCALE/2;
    word32_use_fixed = 1'b0;
    word32_fixed_value = 32'h00000000;
  end

  modport cfg ();
endinterface
