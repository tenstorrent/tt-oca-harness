// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns / 1ps

//------------------------------------------------------------------------------
// RO_Jitter_Model
// Behavioral pseudo-random bit generator to emulate RO jitter characteristics.
// Provides controllable bias, correlation, and stuck-at behavior.
//------------------------------------------------------------------------------
module RO_Jitter_Model #(
  parameter int PROB_SCALE = 1_000_000  // Probability scale for fixed-point params
) (
  input  logic              clk_i,           // Sampling clock (e.g., rosc_sample_clk_i)
  input  logic              rstn_i,          // Active-low reset

  // Configuration
  input  logic              cfg_enable_i,    // Enable output updates on each clk_i edge
  input  logic              cfg_seed_en_i,   // Pulse to reseed PRNG
  input  int unsigned       cfg_seed_i,      // Seed value
  input  int unsigned       cfg_p_bias_i,    // Probability of '1' when independent (0..PROB_SCALE)
  input  int unsigned       cfg_p_corr_i,    // Probability current bit == previous (0..PROB_SCALE)
  input  logic              cfg_stuck_en_i,  // Force stuck-at output
  input  logic              cfg_stuck_value_i, // Value when stuck

  // Outputs
  output logic              bit_o,           // Output bit
  output logic              vld_o            // Valid each sample cycle
);

  // Internal state
  logic prev_bit_q;
  // Sanitized config at module scope: some simulators reject declarations inside always blocks
  logic        _enable_d;
  logic        _stuck_en_d;
  logic        _stuck_val_d;
  int unsigned _p_bias_d;
  int unsigned _p_corr_d;
  // One-cycle pipeline of enable to generate vld one clock after enable
  logic        _enable_q;

  // One-shot initializer to avoid X propagation without adding another driver
  logic init_done;

  // Reseed PRNG when requested
  always_ff @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      // Initialize global PRNG deterministically based on reset and seed value
      void'($urandom(32'h1));
    end else begin
      if (cfg_seed_en_i) begin
        // Guard against seed == 0 (some simulators warn/ignore zero seeds)
        int unsigned _seed = (cfg_seed_i == 0) ? 32'h1 : cfg_seed_i;
        void'($urandom(_seed));
      end
    end
  end

  // Sanitize potentially unknown config inputs and clamp probabilities to
  // PROB_SCALE; the always_ff below only reads these.
  always_comb begin
    _enable_d    = (cfg_enable_i      === 1'b1);
    _stuck_en_d  = (cfg_stuck_en_i    === 1'b1);
    _stuck_val_d = (cfg_stuck_value_i === 1'b1);
    _p_bias_d    = (cfg_p_bias_i > PROB_SCALE) ? PROB_SCALE : cfg_p_bias_i;
    _p_corr_d    = (cfg_p_corr_i > PROB_SCALE) ? PROB_SCALE : cfg_p_corr_i;
  end

  // Main generation
  always_ff @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      bit_o <= 1'b0;
      vld_o <= 1'b0;
      prev_bit_q <= 1'b0;
      init_done <= 1'b0;
      _enable_q <= 1'b0;
    end else begin
      // Initialize outputs once after power-up if reset is never asserted
      if (init_done !== 1'b1) begin
        bit_o      <= 1'b0;
        vld_o      <= 1'b0;
        prev_bit_q <= 1'b0;
        init_done  <= 1'b1;
        _enable_q  <= 1'b0;
      end
      vld_o <= 1'b0;

      // Generate valid one clock after enable is observed
      // IMPORTANT: bit_o and vld_o must be synchronized!
      // Both use _enable_q (delayed enable) so they update together
      vld_o   <= _enable_q;
      _enable_q <= _enable_d;

      if (_enable_q) begin
        if (_stuck_en_d) begin
          bit_o <= _stuck_val_d;
        end else begin
          if ($urandom_range(0, PROB_SCALE - 1) < _p_corr_d) begin
            bit_o <= prev_bit_q;
          end else begin
            bit_o <= ($urandom_range(0, PROB_SCALE - 1) < _p_bias_d);
          end
        end
        prev_bit_q <= bit_o;
      end
    end
  end

endmodule
