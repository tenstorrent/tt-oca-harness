// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AND-OR 2-2-2 Gate
//
//--------------------------------------------------
module prim_ao222 (
  input  a0_i,
  input  a1_i,
  input  b0_i,
  input  b1_i,
  input  c0_i,
  input  c1_i,
  output out_o
);

  assign out_o = (a0_i & a1_i) | (b0_i & b1_i) | (c0_i & c1_i);

endmodule
