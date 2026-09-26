// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// NAND four single-bit inputs onto out_o.
//
// Drive out_o with the bitwise NAND of in0_i through in3_i.

module prim_nand4 (
  input  in0_i,  // First NAND input.
  input  in1_i,  // Second NAND input.
  input  in2_i,  // Third NAND input.
  input  in3_i,  // Fourth NAND input.
  output out_o   // NAND of in0_i through in3_i.
);
  assign out_o = ~(in0_i & in1_i & in2_i & in3_i);

endmodule
