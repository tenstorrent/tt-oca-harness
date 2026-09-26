// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Compare two 256-bit token digests with hard-cell differential equal and not-equal trees.
//
// Equal path (match_p_o): per-bit XNOR then radix-4 NAND/NOR reduction.
// Not-equal path (match_n_o): per-bit XOR then radix-4 OR4 reduction.
// Hard cells prevent synthesis from merging or optimizing away the compare logic (~682
// cells per instance).

module efuse_token_digest_comparator #(
  localparam int unsigned TokenWidth = 256,  // Token digest width in bits.
  localparam int unsigned L0Width    = TokenWidth / 4,  // Token digest width in bits.
  localparam int unsigned L1Width    = L0Width / 4,  // First reduction-tree width.
  localparam int unsigned L2Width    = L1Width / 4  // Second reduction-tree width.
) (
  input  logic [TokenWidth-1:0] token_digest_i,  // Computed 256-bit token digest.
  input  logic [TokenWidth-1:0] token_expected_i,  // Expected 256-bit token digest.

  output logic                  match_p_o,  // 1 = equal.
  output logic                  match_n_o  // 1 = not equal.
);

  //-------------------------------------------------------------------------
  // Equal datapath: XNOR leaves + radix-4 NAND/NOR reduction tree.
  //-------------------------------------------------------------------------
  logic [TokenWidth-1:0] bit_eq;
  logic [L0Width-1:0]    eq_l0;
  logic [L1Width-1:0]    eq_l1;
  logic [L2Width-1:0]    eq_l2;

  // XNOR all the bits, this is the first level of the reduction tree
  // If all the bits are the same, then the output will be a 1, otherwise it will be a 0
  for (genvar i = 0; i < TokenWidth; i++) begin : gen_bit_eq
    prim_xnor2 #(
      .Width(1)
    ) u_xnor_d0nt_touch (
      .in0_i(token_digest_i[i]),
      .in1_i(token_expected_i[i]),
      .out_o(bit_eq[i])
    );
  end

  // L0: Use NAND gates to reduce the 256 bits to 64 bits
  // If all the bits are a 1, then the output will be a 0, this is indicative of a match
  for (genvar g = 0; g < L0Width; g++) begin : gen_eq_l0
    prim_nand4 u_nand_l0_d0nt_touch (
      .in0_i(bit_eq[4*g + 0]),
      .in1_i(bit_eq[4*g + 1]),
      .in2_i(bit_eq[4*g + 2]),
      .in3_i(bit_eq[4*g + 3]),
      .out_o(eq_l0[g])
    );
  end

  // L1: Use NOR gates to reduce the 64 bits to 16 bits
  // If all the input bits are a 0, then the output will be a 1, this is indicative of a match
  for (genvar g = 0; g < L1Width; g++) begin : gen_eq_l1
    prim_nor4 u_nor_l1_d0nt_touch (
      .in0_i(eq_l0[4*g + 0]),
      .in1_i(eq_l0[4*g + 1]),
      .in2_i(eq_l0[4*g + 2]),
      .in3_i(eq_l0[4*g + 3]),
      .out_o(eq_l1[g])
    );
  end

  // L2: Use NAND gates to reduce the 16 bits to 4 bits
  // If all the input bits are a 1, then the output will be a 0, this is indicative of a match
  for (genvar g = 0; g < L2Width; g++) begin : gen_eq_l2
    prim_nand4 u_nand_l2_d0nt_touch (
      .in0_i(eq_l1[4*g + 0]),
      .in1_i(eq_l1[4*g + 1]),
      .in2_i(eq_l1[4*g + 2]),
      .in3_i(eq_l1[4*g + 3]),
      .out_o(eq_l2[g])
    );
  end

  // L3: Use NOR gates to reduce the 4 bits to 1 bit
  // If the input bits are all a 0, then the output will be a 1, this is indicative of a match
  prim_nor4 u_nor_l3_d0nt_touch (
    .in0_i(eq_l2[0]),
    .in1_i(eq_l2[1]),
    .in2_i(eq_l2[2]),
    .in3_i(eq_l2[3]),
    .out_o(match_p_o)
  );

  //-------------------------------------------------------------------------
  // Not-equal datapath: XOR leaves + radix-4 OR4 reduction tree.
  //-------------------------------------------------------------------------
  logic [TokenWidth-1:0] bit_neq;
  logic [L0Width-1:0]    neq_l0;
  logic [L1Width-1:0]    neq_l1;
  logic [L2Width-1:0]    neq_l2;

  for (genvar i = 0; i < TokenWidth; i++) begin : gen_bit_neq
    prim_xor2 #(
      .Width(1)
    ) u_xor_d0nt_touch (
      .in0_i(token_digest_i[i]),
      .in1_i(token_expected_i[i]),
      .out_o(bit_neq[i])
    );
  end

  for (genvar g = 0; g < L0Width; g++) begin : gen_neq_l0
    prim_or4 u_or_l0_d0nt_touch (
      .in0_i(bit_neq[4*g + 0]),
      .in1_i(bit_neq[4*g + 1]),
      .in2_i(bit_neq[4*g + 2]),
      .in3_i(bit_neq[4*g + 3]),
      .out_o(neq_l0[g])
    );
  end

  for (genvar g = 0; g < L1Width; g++) begin : gen_neq_l1
    prim_or4 u_or_l1_d0nt_touch (
      .in0_i(neq_l0[4*g + 0]),
      .in1_i(neq_l0[4*g + 1]),
      .in2_i(neq_l0[4*g + 2]),
      .in3_i(neq_l0[4*g + 3]),
      .out_o(neq_l1[g])
    );
  end

  for (genvar g = 0; g < L2Width; g++) begin : gen_neq_l2
    prim_or4 u_or_l2_d0nt_touch (
      .in0_i(neq_l1[4*g + 0]),
      .in1_i(neq_l1[4*g + 1]),
      .in2_i(neq_l1[4*g + 2]),
      .in3_i(neq_l1[4*g + 3]),
      .out_o(neq_l2[g])
    );
  end

  prim_or4 u_or_l3_d0nt_touch (
    .in0_i(neq_l2[0]),
    .in1_i(neq_l2[1]),
    .in2_i(neq_l2[2]),
    .in3_i(neq_l2[3]),
    .out_o(match_n_o)
  );

endmodule : efuse_token_digest_comparator
