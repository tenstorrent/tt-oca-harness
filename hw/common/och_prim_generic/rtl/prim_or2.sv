// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 2-Input OR Gate
//
//--------------------------------------------------
module prim_or2 (
  input  in0_i,
  input  in1_i,
  output out_o
);

  assign out_o = in0_i | in1_i;

endmodule



