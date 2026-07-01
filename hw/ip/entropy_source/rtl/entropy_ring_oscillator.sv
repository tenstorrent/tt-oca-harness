// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Ring Oscillator
//
// Description:
// This module implements an asynchronous ring oscillator composed of buffer
// cells. Oscillation proceeds when the enable pin is asserted high. The
// oscillation frequency is based on the number of buffers in the delay chain.
// The frequency can be lowered by asserting the detune input high.
//------------------------------------------------------------------------------


module entropy_ring_oscillator #(
    parameter int unsigned TOTAL_LENGTH  = 17,
    parameter int unsigned TAPPED_LENGTH = 13
) (
    input  logic enable_i, // program with config register
    input  logic detune_i, // program with config register
    output logic noise_o
);

    logic [TOTAL_LENGTH-1:0] stage_o;
    logic [TOTAL_LENGTH-1:0] inv0_o;
    logic                    feedback;

    // first delay cell is inverting and has enable input
    gnand2 en (
        .a_i (enable_i),
        .b_i (feedback),
        .z_o (stage_o[0])
    );

    // remaining buffer delay chain TOTAL_LENGTH-1
    generate
        for (genvar i = 1; i < TOTAL_LENGTH; i++) begin : g_dly
            gbuff bf (
                .d_i (stage_o[i-1]),
                .z_o (stage_o[i])
            );
        end
    endgenerate

    // select full length or tapped length for feedback
    gmux2 tap (
        .i0_i (stage_o[TAPPED_LENGTH-1]),
        .i1_i (stage_o[TOTAL_LENGTH-1]),
        .s_i  (detune_i),
        .z_o  (feedback)
    );

    // buffer ring output to manage load
    gbuff fbf (
        .d_i (feedback),
        .z_o (noise_o)
    );

endmodule
