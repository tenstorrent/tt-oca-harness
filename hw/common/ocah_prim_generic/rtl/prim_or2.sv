// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR two single-bit inputs onto out_o.
//
// Drive out_o with the bitwise OR of in0_i and in1_i.

module prim_or2 (
  input  in0_i,  // First OR input.
  input  in1_i,  // Second OR input.
  output out_o   // OR of in0_i and in1_i.
);
  assign out_o = in0_i | in1_i;

endmodule


