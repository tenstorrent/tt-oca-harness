// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

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
        .clk_i  (in),
        .en_i   (en),
        .te_i   (test_en),
        .clk_o  (out)
    );

endmodule
