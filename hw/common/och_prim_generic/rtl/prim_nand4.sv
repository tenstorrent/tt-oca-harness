// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-Input NAND Gate
//
//--------------------------------------------------
module prim_nand4 (
  input  in0_i,
  input  in1_i,
  input  in2_i,
  input  in3_i,
  output out_o
);

  assign out_o = ~(in0_i & in1_i & in2_i & in3_i);

endmodule
