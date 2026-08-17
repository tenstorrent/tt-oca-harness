// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Triple-Redundant Token Digest Comparator Wrapper
//
// Wraps three efuse_token_digest_comparator instances to maintain triple
// redundancy. Each instance performs an independent 256-bit comparison using
// hard-cell primitives (XNOR/XOR + NAND/NOR/OR reduction trees), preventing
// synthesis from optimizing the three compare cones into one.
//
// Output encoding:
//   token_match_o = {match_n[2], match_p[2], match_n[1], match_p[1], match_n[0], match_p[0]}
//   Match    = 6'b010101  (compute_vld=1, tokens equal)
//   No match = 6'b101010  (compute_vld=1, tokens differ)
//   Error    = 6'b111111  (compute_vld=1, redundancy fault)
//   Idle     = 6'b000000  (compute_vld=0)
//
// This is not a majority vote: all three instances must agree and each must
// drive a legal differential pair. Any deviation raises redundancy_fault_o,
// which may indicate a fault injection or FIB attack, and forces the error
// code onto every output bit so downstream feature gating fails closed.
//-----------------------------------------------------------------------------

`include "prim_assert.sv"

module efuse_triple_redundant_comparator #(
    localparam int TokenWidth = 256
) (
    input  logic                   compute_comparison_vld_i,
    input  logic [TokenWidth-1:0]  token_digest_i,
    input  logic [TokenWidth-1:0]  token_expected_i,
    output logic [5:0]             token_match_o,
    output logic                   redundancy_fault_o
);

    logic [2:0] match_p_raw, match_n_raw;
    logic [2:0] match_p, match_n;
    logic [5:0] match_bus;
    logic [2:0] pair_bad;
    logic [1:0] disagree_p, disagree_n;
    logic       fault_lo, fault_hi, fault_raw;

    // Three independent token digest comparators.
    for (genvar i = 0; i < 3; i++) begin : gen_token_digest_comparators
        efuse_token_digest_comparator u_token_digest_comparator (
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

    assign match_bus = {match_n[2], match_p[2], match_n[1], match_p[1], match_n[0], match_p[0]};

    //-------------------------------------------------------------------------
    // Redundancy fault detection, built from the same hard-cell primitives as
    // the compare cones so synthesis cannot merge the detector into them.
    //
    // With compute_comparison_vld_i asserted only two encodings are legal, so a
    // fault is either an instance whose differential pair collapsed
    // (match_p == match_n) or two instances that disagree.
    //-------------------------------------------------------------------------
    for (genvar i = 0; i < 3; i++) begin : gen_pair_check
        prim_xnor2 #(
            .Width(1)
        ) u_pair_bad_d0nt_touch (
            .in0_i(match_p[i]),
            .in1_i(match_n[i]),
            .out_o(pair_bad[i])
        );
    end

    for (genvar i = 0; i < 2; i++) begin : gen_disagree_check
        prim_xor2 #(
            .Width(1)
        ) u_disagree_p_d0nt_touch (
            .in0_i(match_p[i]),
            .in1_i(match_p[i+1]),
            .out_o(disagree_p[i])
        );

        prim_xor2 #(
            .Width(1)
        ) u_disagree_n_d0nt_touch (
            .in0_i(match_n[i]),
            .in1_i(match_n[i+1]),
            .out_o(disagree_n[i])
        );
    end

    prim_or4 u_fault_lo_d0nt_touch (
        .in0_i(pair_bad[0]),
        .in1_i(pair_bad[1]),
        .in2_i(pair_bad[2]),
        .in3_i(disagree_p[0]),
        .out_o(fault_lo)
    );

    prim_or4 u_fault_hi_d0nt_touch (
        .in0_i(disagree_p[1]),
        .in1_i(disagree_n[0]),
        .in2_i(disagree_n[1]),
        .in3_i(1'b0),
        .out_o(fault_hi)
    );

    prim_or2 u_fault_raw_d0nt_touch (
        .in0_i(fault_lo),
        .in1_i(fault_hi),
        .out_o(fault_raw)
    );

    // Idle collapses every pair to zero, so the fault term only means anything
    // once a comparison is in flight.
    prim_and2 #(
        .Width(1)
    ) u_fault_gate_d0nt_touch (
        .in0_i(compute_comparison_vld_i),
        .in1_i(fault_raw),
        .out_o(redundancy_fault_o)
    );

    // The error code is all ones, so forcing it is a per-bit OR with the fault.
    for (genvar i = 0; i < 6; i++) begin : gen_force_error_code
        prim_or2 u_force_error_d0nt_touch (
            .in0_i(match_bus[i]),
            .in1_i(redundancy_fault_o),
            .out_o(token_match_o[i])
        );
    end

endmodule : efuse_triple_redundant_comparator
