// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-Input AND Gate
//
//--------------------------------------------------
module prim_and3 (
  input  in0_i,
  input  in1_i,
  input  in2_i,
  output out_o
);
  assign out_o = in0_i & in1_i & in2_i;
endmodule
