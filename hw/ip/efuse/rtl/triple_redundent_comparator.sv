// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Triple-Redundant Comparator
// Compares a token digest to an expected token using three fully independent,
// redundant matchers. Each instance outputs a differential 2-bit match signal
// ({match_n, match_p}), for a total of 6 bits. This mitigates fault injection
// or FIB tampering by requiring all three comparators to individually agree.
// Not a majority-voting scheme: any discrepancy between the comparators
// signals a mismatch, indicating possible tampering and triggering an alarm.
// Differential encoding (01 = match, 10 = no match) flags stuck-at or illegal states.
//
//-----------------------------------------------------------------------------


module triple_redundent_comparator
#(
    parameter logic [1:0] HASH_PASS = 2'b01,
    parameter logic [1:0] HASH_FAIL = 2'b10,

    parameter type data_t = logic,
    parameter int unsigned DATA_WIDTH = 256
) (
    input  logic                  compute_comparison_vld_i,
    input  logic [DATA_WIDTH-1:0] token_digest_i,
    input  logic [DATA_WIDTH-1:0] token_expected_i,

    output logic [5:0]            token_match_o
);

    // Define valid differential encoding constants
    localparam logic [1:0] DIFF_MATCH    = 2'b01;  // Match: {match_n=0, match_p=1}
    localparam logic [1:0] DIFF_NO_MATCH = 2'b10;  // No match: {match_n=1, match_p=0}
    // Invalid states that indicate tampering:
    // 2'b00 - both low (stuck-at-0 fault)
    // 2'b11 - both high (stuck-at-1 fault)

    // Triple-redundant comparators for RMA SOP token
    // Each comparator independently generates both match_p and match_n
    logic [2:0] match_p, match_n;

    // Comparator 0 (dont_touch)
    prim_and2 #(
        .Width(1)
    ) u_match_p_0_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(token_digest_i == token_expected_i),
        .out_o(match_p[0])
    );

    prim_and2 #(
        .Width(1)
    ) u_match_n_0_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(token_digest_i != token_expected_i),
        .out_o(match_n[0])
    );

    // Comparator 1 (dont_touch)
    prim_and2 #(
        .Width(1)
    ) u_match_p_1_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(token_digest_i == token_expected_i),
        .out_o(match_p[1])
    );

    prim_and2 #(
        .Width(1)
    ) u_match_n_1_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(token_digest_i != token_expected_i),
        .out_o(match_n[1])
    );

    // Comparator 2 (dont_touch)
    prim_and2 #(
        .Width(1)
    ) u_match_p_2_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(token_digest_i == token_expected_i),
        .out_o(match_p[2])
    );

    prim_and2 #(
        .Width(1)
    ) u_match_n_2_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(token_digest_i != token_expected_i),
        .out_o(match_n[2])
    );

    // Match = 6'b010101
    // Mismatch = 6'b101010
    // Error = 6'b111111

    assign token_match_o = {match_n[2], match_p[2], match_n[1], match_p[1], match_n[0], match_p[0]};

endmodule : triple_redundent_comparator
