// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-Input OR Gate
//
//--------------------------------------------------
module prim_or4 (
  input  in0_i,
  input  in1_i,
  input  in2_i,
  input  in3_i,
  output out_o
);

  assign out_o = in0_i | in1_i | in2_i | in3_i;

endmodule
