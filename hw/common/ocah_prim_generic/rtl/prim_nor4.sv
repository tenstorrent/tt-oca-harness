// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// NOR four single-bit inputs onto out_o.
//
// Drive out_o with the bitwise NOR of in0_i through in3_i.

module prim_nor4 (
  input  in0_i,  // First NOR input.
  input  in1_i,  // Second NOR input.
  input  in2_i,  // Third NOR input.
  input  in3_i,  // Fourth NOR input.
  output out_o   // NOR of in0_i through in3_i.
);
  assign out_o = ~(in0_i | in1_i | in2_i | in3_i);

endmodule
