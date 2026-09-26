// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR four single-bit inputs onto out_o.
//
// Drive out_o with the bitwise OR of in0_i through in3_i.

module prim_or4 (
  input  in0_i,  // First OR input.
  input  in1_i,  // Second OR input.
  input  in2_i,  // Third OR input.
  input  in3_i,  // Fourth OR input.
  output out_o   // OR of in0_i through in3_i.
);
  assign out_o = in0_i | in1_i | in2_i | in3_i;

endmodule
