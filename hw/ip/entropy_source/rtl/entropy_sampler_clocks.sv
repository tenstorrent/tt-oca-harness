// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Sampler Clocks
//
// Description:
// Each noise generating ring oscillator's sampling clock can be
// individually selected to be either the external sampling clock (default)
// or a shared ring oscillator (length 109, detunable to 101) if the
// corresponding sample_clk_select bit is asserted to high.
//
// The single shared sampling ring oscillator is distributed to all 12
// generators, providing area and power savings while maintaining per-generator
// clock selection and programmable division (÷1, ÷2, ÷4, ÷8, ÷16, ÷32).
//
// The shared RO is enabled if ANY generator is enabled, and detunes if ANY
// generator requests detune (OR-based control for backward compatibility).
//------------------------------------------------------------------------------


module entropy_sampler_clocks #(
    parameter int unsigned NRINGS = 12
) (
    input  logic                      clk_i,
    input  logic                      rst_ni,
    input  logic                      sample_clk_i,
    input  logic [NRINGS-1:0]         sample_clk_select_i,
    input  logic [NRINGS-1:0]         enable_i,
    input  logic [NRINGS-1:0]         detune_ro_i,
    input  logic [NRINGS-1:0][4:0]    sample_clk_divide_i, // Per-generator clock division: 0=÷1, 1=÷2, 2=÷4, 3=÷8, 4=÷16, 5=÷32
    output logic [NRINGS-1:0]         sample_clk_o
);

    // Single shared sampling ring oscillator for all 12 generators
    // Length 109 (normal) and 53 (detuned) chosen to achieve approximately 10x
    // frequency ratio with noise generating ring oscillators
    localparam int unsigned SHARED_TOTAL_LENGTH  = 109;
    localparam int unsigned SHARED_TAPPED_LENGTH = 53;

    logic shared_ring_osc_clk;
    logic shared_detune_enable;

    // Aggregate detune control: shared RO detunes if ANY generator requests it
    // This maintains backward compatibility with per-generator detune registers
    assign shared_detune_enable = |detune_ro_i;

    // Shared ring oscillator instance
    entropy_ring_oscillator #(
        .TOTAL_LENGTH (SHARED_TOTAL_LENGTH),
        .TAPPED_LENGTH(SHARED_TAPPED_LENGTH)
    ) shared_ro (
        .enable_i(|enable_i),  // Enable if ANY generator is enabled
        .detune_i(shared_detune_enable),
        .noise_o (shared_ring_osc_clk)
    );
    logic [NRINGS-1:0] selected_clk;
    logic [NRINGS-1:0][5:0] sample_clk_divided; // [i][0]=÷1, [i][1]=÷2, [i][2]=÷4, [i][3]=÷8, [i][4]=÷16, [i][5]=÷32

    generate
        for (genvar i = 0; i < NRINGS; i++) begin : g_ecmplx
            // Select between external clock and SHARED ring oscillator
            assign selected_clk[i] = sample_clk_select_i[i] ? shared_ring_osc_clk : sample_clk_i;

            // Ripple divider for programmable clock division
            // NUM_STAGES=5 provides division factors: 1, 2, 4, 8, 16, 32
            entropy_ripple_divider #(
                .NUM_STAGES(5)
            ) u_sample_clk_divider (
                .rst_ni  (rst_ni),
                .clk_i   (selected_clk[i]),
                .div_o   (sample_clk_divided[i])
            );

            // Select divided sample clock based on configuration
            // sample_clk_divide_i[i]: 0=÷1, 1=÷2, 2=÷4, 3=÷8, 4=÷16, 5=÷32
            always_comb begin
                case (sample_clk_divide_i[i])
                    5'd0:    sample_clk_o[i] = sample_clk_divided[i][0]; // ÷1
                    5'd1:    sample_clk_o[i] = sample_clk_divided[i][1]; // ÷2
                    5'd2:    sample_clk_o[i] = sample_clk_divided[i][2]; // ÷4
                    5'd3:    sample_clk_o[i] = sample_clk_divided[i][3]; // ÷8
                    5'd4:    sample_clk_o[i] = sample_clk_divided[i][4]; // ÷16
                    5'd5:    sample_clk_o[i] = sample_clk_divided[i][5]; // ÷32
                    default: sample_clk_o[i] = sample_clk_divided[i][2]; // ÷4 (default)
                endcase
            end
        end
    endgenerate

endmodule
