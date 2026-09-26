// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Gate clocks for Chipyard-generated SMC CPU designs.
//
// Adapts prim_clkgater to the EICG_wrapper port names Chipyard emits.
// test_en bypasses gating so scan and DFT can drive the clock freely.

module EICG_wrapper (
    input  logic in,                    // Clock input.
    input  logic test_en,               // Test enable.
    input  logic en,                    // Clock enable.
    output logic out                    // Gated clock output.
);

    prim_clkgater u_clkgater (
        .clk_i  (in),
        .en_i   (en),
        .te_i   (test_en),
        .clk_o  (out)
    );

endmodule
