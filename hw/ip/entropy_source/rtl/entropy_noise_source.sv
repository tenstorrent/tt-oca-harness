// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Sample an asynchronous ring oscillator through a metastable flop into the system clock domain.
//
// TOTAL_LENGTH and TAPPED_LENGTH size the RO; enable_i starts oscillation; detune_i high
// selects the full-length feedback path and low the shorter tap.
// sample_clk_i clocks the metastable sample; the bit is double-synchronized onto clk_i as
// noise_o.

module entropy_noise_source #(
  parameter int unsigned TOTAL_LENGTH  = 17,  // Full ring-oscillator stage count.
  parameter int unsigned TAPPED_LENGTH = 13  // Stage count of the shorter feedback tap, used while
                                             // detune_i is low.
) (
  input       logic clk_i,              // System clock.
  input       logic rst_ni,             // Active-low asynchronous reset of the sample and
                                        // synchronizer flops.
  input       logic sample_clk_i,       // Clock of the flop that samples the asynchronous ring
                                        // output.
  input       logic enable_i,           // Enables the ring oscillator; while low its output is
                                        // static.
  input       logic detune_i,           // High selects the ring's full TOTAL_LENGTH feedback path,
                                        // low the shorter TAPPED_LENGTH tap.
  output      logic noise_o             // Ring-oscillator sample, double-synchronized onto clk_i.
);

  /////////////
  // Signals
  /////////////

  logic noise_async;
  logic noise_sample;
  logic [1:0] noise_sync;

  /////////////////
  // Sub-instances
  /////////////////

  entropy_ring_oscillator #(
    .TOTAL_LENGTH  (TOTAL_LENGTH),
    .TAPPED_LENGTH (TAPPED_LENGTH)
  ) u_ring_oscillator (
    .enable_i,
    .detune_i,
    .noise_o  (noise_async)
  );

  // Metastable sample flip-flop — intentional async capture of RO output
  prim_flop u_smpl (
    .clk_i (sample_clk_i),
    .d_i  (noise_async),
    .rst_ni (rst_ni),
    .q_o  (noise_sample)
  );

  // Two-flop synchroniser
  prim_flop u_sync0 (
    .clk_i (clk_i),
    .d_i  (noise_sample),
    .rst_ni (rst_ni),
    .q_o  (noise_sync[0])
  );

  prim_flop u_sync1 (
    .clk_i (clk_i),
    .d_i  (noise_sync[0]),
    .rst_ni (rst_ni),
    .q_o  (noise_sync[1])
  );

  ///////////
  // Output
  ///////////

  assign noise_o = noise_sync[1];

endmodule
