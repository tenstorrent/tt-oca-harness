// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_ring_oscillator.sv
 * @brief Asynchronous ring oscillator with configurable delay chain length.
 *
 * @details This module implements an asynchronous ring oscillator composed of
 *          buffer cells arranged in a delay chain. Oscillation proceeds when
 *          the enable pin is asserted high. The oscillation frequency is based
 *          on the number of buffers in the delay chain. The frequency can be
 *          lowered by asserting the detune input high, which selects a shorter
 *          feedback path via an internal multiplexer.
 *
 * @param TOTAL_LENGTH   Total number of buffer stages in the delay chain.
 *                       Default: 17
 * @param TAPPED_LENGTH  Number of stages before the tap point for detuning.
 *                       Default: 13
 */

module entropy_ring_oscillator #(
  parameter int unsigned TOTAL_LENGTH  = 17,
  parameter int unsigned TAPPED_LENGTH = 13
) (
  input  logic enable_i, // program with config register
  input  logic detune_i, // program with config register
  output logic noise_o
);

  logic [TOTAL_LENGTH-1:0] stage_o;
  logic                    feedback;

  // first delay cell is inverting and has enable input
  entropy_ring_nand2_wrapper u_en (
    .a1_i (enable_i),
    .a2_i (feedback),
    .y_o  (stage_o[0])
  );

  // remaining buffer delay chain TOTAL_LENGTH-1
  generate
    for (genvar i = 1; i < TOTAL_LENGTH; i++) begin : gen_dly
      entropy_ring_buf_wrapper u_bf (
        .a_i (stage_o[i-1]),
        .y_o (stage_o[i])
      );
    end
  endgenerate

  // select full length or tapped length for feedback
  entropy_ring_mux2_wrapper u_tap (
    .i0_i  (stage_o[TAPPED_LENGTH-1]),
    .i1_i  (stage_o[TOTAL_LENGTH-1]),
    .sel_i (detune_i),
    .y_o   (feedback)
  );

  // buffer ring output to manage load
  entropy_ring_buf_wrapper u_fbf (
    .a_i (feedback),
    .y_o (noise_o)
  );

endmodule
