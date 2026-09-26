// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Gate clocks for Chipyard-generated SMC CPU designs.
//
// Adapts prim_clock_gating to the EICG_wrapper port names Chipyard emits.
// test_en bypasses gating so scan and DFT can drive the clock freely; the generated cluster
// ties test_en low on every instance.

module EICG_wrapper (
    input  logic in,                    // Clock input.
    input  logic test_en,               // Active-high test enable; forces the clock on
                                        // regardless of en.
    input  logic en,                    // Active-high clock enable; low holds out low.
    output logic out                    // Gated clock output.
);

    prim_clock_gating u_clkgater (
        .clk_i  (in),
        .en_i   (en),
        .test_en_i (test_en),
        .clk_o  (out)
    );

endmodule
