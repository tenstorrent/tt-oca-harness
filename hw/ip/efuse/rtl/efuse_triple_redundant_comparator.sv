// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap three hard-cell token digest comparators and encode a fail-closed match code.
//
// token_match_o packs {match_n,match_p} for instances 2,1,0.
// Match=6'b010101, no-match=6'b101010, error=6'b111111 when compute_comparison_vld_i is
// 1; idle=6'b000000 when valid is 0.
// Not a majority vote: all three instances must agree with legal differential pairs; any
// deviation asserts redundancy_fault_o and forces the error code so feature gating fails
// closed.

`include "prim_assert.sv"

module efuse_triple_redundant_comparator #(
  localparam int TokenWidth = 256       // Token digest width in bits.
) (
  input  logic                   compute_comparison_vld_i,  // 1 publishes match codes; 0 forces idle 6'b000000.
  input  logic [TokenWidth-1:0]  token_digest_i,  // Computed 256-bit token digest.
  input  logic [TokenWidth-1:0]  token_expected_i,  // Expected 256-bit token digest.
  output logic [5:0]             token_match_o,  // Encoded {match_n,match_p}×3 match/fault/idle code.
  output logic                   redundancy_fault_o  // High when the three comparators disagree or pair illegally.
);

  logic [2:0] match_p_raw, match_n_raw;
  logic [2:0] match_p, match_n;
  logic [5:0] match_bus;
  logic [2:0] pair_bad;
  logic [1:0] disagree_p, disagree_n;
  logic fault_comparator_collapse, fault_comparators_disagree, fault_raw;

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
  // Redundancy fault detection
  //
  // Two kinds of faults:
  // - Differential pair collapsed (match_p[x] == match_n[x])
  // - Two instances that disagree
  //-------------------------------------------------------------------------

  // An instance whose differential pair collapsed, both rails at the same
  // value. XNOR is 1 when the rails are equal, which is the illegal case.
  // ex: match_bus = 6'b010100, instance 0 collapsed to 00
  for (genvar i = 0; i < 3; i++) begin : gen_pair_check
    prim_xnor2 #(
      .Width(1)
    ) u_pair_bad_d0nt_touch (
      .in0_i(match_p[i]),
      .in1_i(match_n[i]),
      .out_o(pair_bad[i])
    );
  end

  // If any instance's differential pair collapsed, then the fault is raised
  prim_or4 u_fault_comparator_collapse_d0nt_touch (
    .in0_i(pair_bad[0]),
    .in1_i(pair_bad[1]),
    .in2_i(pair_bad[2]),
    .in3_i(1'b0),
    .out_o(fault_comparator_collapse)
  );

  // Instances that disagree with each other.
  // ex: match_bus = 6'b010110, instance 0 says differ, instances 1 and 2 say equal
  //
  // Equality is transitive, so comparing adjacent instances covers instance 0 against instance 2.
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

  prim_or4 u_fault_comparators_disagree_d0nt_touch (
    .in0_i(disagree_p[0]),
    .in1_i(disagree_p[1]),
    .in2_i(disagree_n[0]),
    .in3_i(disagree_n[1]),
    .out_o(fault_comparators_disagree)
  );

  prim_or2 u_fault_raw_d0nt_touch (
    .in0_i(fault_comparator_collapse),
    .in1_i(fault_comparators_disagree),
    .out_o(fault_raw)
  );

  // Idle collapses every pair to zero, so the fault term only means anything
  // once a comparison is in flight.
  prim_and2 #(
    .Width(1)
  ) u_fault_gate_d0nt_touch (
    .in0_i(fault_raw),
    .in1_i(compute_comparison_vld_i),
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
