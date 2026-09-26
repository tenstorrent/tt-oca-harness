// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OR two inputs for clock-network use.
//
// Drive out_o with in0_i | in1_i. Kept as a named cell so synthesis can map it to a
// clock-capable OR2.

module prim_clock_or2 (
  input  in0_i,  // First OR input.
  input  in1_i,  // Second OR input.
  output out_o   // OR of in0_i and in1_i.
);
  assign out_o = in0_i | in1_i;

endmodule
