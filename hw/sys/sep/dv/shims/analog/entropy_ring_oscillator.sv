// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Behavioral replacement for the entropy-source analog ring
// oscillator. The real RTL instantiates delay cells in a feedback loop; event-
// driven simulation can spend unbounded time scheduling that analog oscillation.
// OSS entropy tests drive the decorrelator input explicitly with +esrc_noise_force,
// so this shim only provides a deterministic idle value for tests that do not
// exercise the entropy datapath.

module entropy_ring_oscillator #(
  parameter int unsigned TOTAL_LENGTH  = 17,
  parameter int unsigned TAPPED_LENGTH = 13
) (
  input  logic enable_i,
  input  logic detune_i,
  output logic noise_o
);

  logic unused;

  assign unused = enable_i ^ detune_i ^ ^TOTAL_LENGTH ^ ^TAPPED_LENGTH;
  assign noise_o = 1'b0;

endmodule
