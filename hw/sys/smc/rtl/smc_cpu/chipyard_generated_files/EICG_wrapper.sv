// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

// Copyright Tenstorrent Inc.
// Clock gating wrapper for Chipyard-generated designs
// This module wraps the prim_clkgater to match the interface expected by Chipyard

module EICG_wrapper (
    input  logic in,       // Clock input
    input  logic test_en,  // Test enable
    input  logic en,       // Clock enable
    output logic out       // Gated clock output
);

    prim_clkgater u_clkgater (
        .i_clk  (in),
        .i_en   (en),
        .i_te   (test_en),
        .o_clk  (out)
    );

endmodule
