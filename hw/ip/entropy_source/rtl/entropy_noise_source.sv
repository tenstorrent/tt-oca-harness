// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Sample an asynchronous ring-oscillator output through a metastable flop into the system clock
// domain.
//
// sample_clk_i clocks the metastable sample of noise_async_i; the bit is double-synchronized
// onto clk_i as noise_o.

module entropy_noise_source (
  input       logic clk_i,              // System clock.
  input       logic rst_ni,             // Active-low asynchronous reset of the sample and
                                        // synchronizer flops.
  input       logic sample_clk_i,       // Clock of the flop that samples noise_async_i.
  input       logic noise_async_i,      // Ring-oscillator output, asynchronous to both clocks.
  output      logic noise_o             // Ring-oscillator sample, double-synchronized onto clk_i.
);

  /////////////
  // Signals
  /////////////

  logic noise_sample;
  logic [1:0] noise_sync;

  /////////////////
  // Sub-instances
  /////////////////

  // Metastable sample flip-flop — intentional async capture of RO output
  prim_flop u_smpl (
    .clk_i (sample_clk_i),
    .d_i  (noise_async_i),
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
