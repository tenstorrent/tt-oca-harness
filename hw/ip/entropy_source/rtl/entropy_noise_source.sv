// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Noise Source
//
// Description:
// This module implements an entropy noise source based on sampling an
// asynchronous ring oscillator. Noise originates from the oscillator
// phase jitter as well as the metastable events gnerated in the sampling
// flip-flop.
//------------------------------------------------------------------------------

module entropy_noise_source #(
    parameter int unsigned TOTAL_LENGTH  = 17,
    parameter int unsigned TAPPED_LENGTH = 13
) (
    input  logic clk_i,
    input  logic rst_ni,
    input  logic sample_clk_i,
    input  logic enable_i, // program with config register
    input  logic detune_i, // program with config register
    output logic noise_o
);

    logic [TOTAL_LENGTH-1:0] stage_o;
    logic [TOTAL_LENGTH-1:0] inv0_o;
    logic                    feedback;
    logic                    noise_async;
    logic                    noise_sample;
    logic [1:0]              noise_sync;

    entropy_ring_oscillator #(
        .TOTAL_LENGTH  (TOTAL_LENGTH),
        .TAPPED_LENGTH (TAPPED_LENGTH)
    ) ro (
        .enable_i,
        .detune_i,
        .noise_o       (noise_async)
    );

    // sample flip-flop with expectation of metastable behaviour
    gdff smpl (
        .d_i   (noise_async),
        .cdn_i (rst_ni),
        .cp_i  (sample_clk_i),
        .q_o   (noise_sample)
    );

    // synchronize the noise sample for output
    gdff sync0 (
        .d_i   (noise_sample),
        .cdn_i (rst_ni),
        .cp_i  (clk_i),
        .q_o   (noise_sync[0])
    );

    gdff sync1 (
        .d_i   (noise_sync[0]),
        .cdn_i (rst_ni),
        .cp_i  (clk_i),
        .q_o   (noise_sync[1])
    );

    assign noise_o = noise_sync[1];

    // Simulation startup aid: SIMPLE IVERILOG-COMPATIBLE STARTUP
  `ifdef SIMULATION
    initial begin
        $display("IVERILOG RING OSCILLATOR TEST at t=%0t", $time);
        $display("Design: GNAND2(1 inv) + 16 stages x 2inv each = 33 total inversions (odd -> should oscillate)");

        // Simple monitoring without force/release which causes multiple driver issues in iverilog
        #500;  // Wait for circuit to settle
        $display("t=%0t: Circuit should have settled, monitoring natural behavior...", $time);

        repeat (10) begin
            #50;
            $display("t=%0t: stage[0-4]=%b%b%b%b%b feedback=%b enable=%b",
                     $time, stage_o[0], stage_o[1], stage_o[2], stage_o[3], stage_o[4], feedback, enable_i);
        end
    end
  `endif

endmodule
