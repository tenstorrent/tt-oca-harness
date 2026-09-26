// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Copyright Tenstorrent Inc.
// Clock gating wrapper for Chipyard-generated designs
// This module wraps prim_clock_gating to match the interface expected by Chipyard

module EICG_wrapper (
    input  logic in,       // Clock input
    input  logic test_en,  // Test enable
    input  logic en,       // Clock enable
    output logic out       // Gated clock output
);

    prim_clock_gating u_clkgater (
        .clk_i  (in),
        .en_i   (en),
        .test_en_i (test_en),
        .clk_o  (out)
    );

endmodule
