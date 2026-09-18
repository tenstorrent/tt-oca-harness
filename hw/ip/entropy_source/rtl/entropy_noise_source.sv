// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_noise_source.sv
 * @brief Ring-oscillator entropy source with metastable sampling.
 *
 * @details Samples an asynchronous ring oscillator with a metastable D
 *          flip-flop to extract entropy from phase jitter, then double-
 *          synchronises the output to the system clock domain. The RO is
 *          parameterized by total length and number of tapped stages.
 *
 * @param TOTAL_LENGTH  Total ring oscillator length in stages (default: 17)
 * @param TAPPED_LENGTH Number of RO stages used for tapping (default: 13)
 */

module entropy_noise_source #(
  parameter int unsigned TOTAL_LENGTH  = 17,
  parameter int unsigned TAPPED_LENGTH = 13
) (
  input       logic clk_i,
  input       logic rst_ni,
  input       logic sample_clk_i,
  input       logic enable_i,
  input       logic detune_i,
  output      logic noise_o
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
  prim_dffrxq u_smpl (
    .clk_i (sample_clk_i),
    .d_i  (noise_async),
    .rst_ni (rst_ni),
    .q_o  (noise_sample)
  );

  // Two-flop synchroniser
  prim_dffrxq u_sync0 (
    .clk_i (clk_i),
    .d_i  (noise_sample),
    .rst_ni (rst_ni),
    .q_o  (noise_sync[0])
  );

  prim_dffrxq u_sync1 (
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
