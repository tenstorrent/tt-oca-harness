// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// AND three single-bit inputs onto out_o.
//
// Drive out_o with the bitwise AND of in0_i, in1_i, and in2_i. This is the generic
// technology cell used where an AND3 is required.

module prim_and3 (
  input  in0_i,  // First AND input.
  input  in1_i,  // Second AND input.
  input  in2_i,  // Third AND input.
  output out_o   // AND of in0_i, in1_i, and in2_i.
);
  assign out_o = in0_i & in1_i & in2_i;
endmodule
