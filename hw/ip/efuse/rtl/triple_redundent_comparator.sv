// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Triple-Redundant Comparator
//
// Wraps three token_compare_match_hardened instances to maintain triple
// redundancy. Each instance performs an independent 256-bit comparison using
// hard-cell primitives (XNOR/XOR + NAND/NOR/OR reduction trees), preventing
// synthesis from CSE-ing the three compare cones into one.
//
// Output encoding:
//   token_match_o = {match_n[2], match_p[2], match_n[1], match_p[1], match_n[0], match_p[0]}
//   Match    = 6'b010101  (compute_vld=1, tokens equal)
//   No match = 6'b101010  (compute_vld=1, tokens differ)
//   Idle     = 6'b000000  (compute_vld=0)
//-----------------------------------------------------------------------------

`include "prim_assert.sv"

module triple_redundent_comparator #(
    parameter logic [1:0]  HASH_PASS  = 2'b01,
    parameter logic [1:0]  HASH_FAIL  = 2'b10,
    parameter type         data_t     = logic,
    parameter int unsigned DATA_WIDTH = 256
) (
    input  logic                   compute_comparison_vld_i,
    input  logic [DATA_WIDTH-1:0]  token_digest_i,
    input  logic [DATA_WIDTH-1:0]  token_expected_i,
    output logic [5:0]             token_match_o
);

    logic [2:0] match_p_raw, match_n_raw;
    logic [2:0] match_p, match_n;

    // Three independent hardened comparators.
    // The full DATA_WIDTH comparison lives inside hard-cell reduction trees
    // inside each token_compare_match_hardened instance, so synthesis cannot
    // common-subexpression the three compare cones.
    for (genvar i = 0; i < 3; i++) begin : gen_hardened_comparators
        token_compare_match_hardened #(
            .TOKEN_WIDTH(DATA_WIDTH)
        ) u_comparator (
            .token_digest_i   (token_digest_i),
            .token_expected_i (token_expected_i),
            .match_p_o        (match_p_raw[i]),
            .match_n_o        (match_n_raw[i])
        );

        prim_and2 #(
            .Width(1)
        ) u_gate_p_d0nt_touch (
            .in0_i(compute_comparison_vld_i),
            .in1_i(match_p_raw[i]),
            .out_o(match_p[i])
        );

        prim_and2 #(
            .Width(1)
        ) u_gate_n_d0nt_touch (
            .in0_i(compute_comparison_vld_i),
            .in1_i(match_n_raw[i]),
            .out_o(match_n[i])
        );
    end

    assign token_match_o = {match_n[2], match_p[2], match_n[1], match_p[1], match_n[0], match_p[0]};

endmodule : triple_redundent_comparator
