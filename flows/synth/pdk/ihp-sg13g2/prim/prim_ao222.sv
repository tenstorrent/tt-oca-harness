// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR three two-input ANDs.
//
// The cell library has no AO222: an sg13g2_a22oi_1 and an sg13g2_nand2_1 form the inverted
// terms and an sg13g2_nand2_1 combines them.
module prim_ao222 (
  input  logic a0_i,  // First input of the first AND term.
  input  logic a1_i,  // Second input of the first AND term.
  input  logic b0_i,  // First input of the second AND term.
  input  logic b1_i,  // Second input of the second AND term.
  input  logic c0_i,  // First input of the third AND term.
  input  logic c1_i,  // Second input of the third AND term.
  output logic out_o  // OR of the three AND terms.
);
  logic ab_n, c_n;

  (* dont_touch = "true" *)
  sg13g2_a22oi_1 u_ab (
    .A1      (a0_i),
    .A2      (a1_i),
    .B1      (b0_i),
    .B2      (b1_i),
    .Y       (ab_n)
  );

  (* dont_touch = "true" *)
  sg13g2_nand2_1 u_c (
    .A       (c0_i),
    .B       (c1_i),
    .Y       (c_n)
  );

  (* dont_touch = "true" *)
  sg13g2_nand2_1 u_out (
    .A       (ab_n),
    .B       (c_n),
    .Y       (out_o)
  );
endmodule
