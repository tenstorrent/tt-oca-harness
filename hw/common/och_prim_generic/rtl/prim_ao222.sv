// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR three 2-input AND products onto out_o.
//
// Compute (a0_i & a1_i) | (b0_i & b1_i) | (c0_i & c1_i). Maps to a technology AO222 when
// the library provides one.

module prim_ao222 (
  input  a0_i,  // First input of AND term A.
  input  a1_i,  // Second input of AND term A.
  input  b0_i,  // First input of AND term B.
  input  b1_i,  // Second input of AND term B.
  input  c0_i,  // First input of AND term C.
  input  c1_i,  // Second input of AND term C.
  output out_o  // OR of the three AND products.
);
  assign out_o = (a0_i & a1_i) | (b0_i & b1_i) | (c0_i & c1_i);

endmodule
