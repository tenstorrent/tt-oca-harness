// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Oscillate an asynchronous buffer ring with an optional detuned feedback tap.
//
// enable_i high closes the delay chain so it oscillates; frequency follows the number of
// buffer stages.
// detune_i high selects the full TOTAL_LENGTH feedback path through an internal mux, which
// lowers frequency; detune_i low selects the shorter TAPPED_LENGTH tap.

module entropy_ring_oscillator #(
  parameter int unsigned TOTAL_LENGTH  = 17,  // Full ring-oscillator stage count.
  parameter int unsigned TAPPED_LENGTH = 13  // Stage count of the shorter feedback tap, used while
                                             // detune_i is low.
) (
  input  logic enable_i,                // High lets the ring oscillate; low holds the NAND stage
                                        // output high.
  input  logic detune_i,                // Feedback select: high for the full TOTAL_LENGTH ring, low
                                        // for the TAPPED_LENGTH tap.
  output logic noise_o                  // Buffered, asynchronous ring-oscillator output.
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
