// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock NAND2 Gate
//
//--------------------------------------------------
module prim_clock_nand2 (
  input  a1_i,
  input  a2_i,
  output y_o
);

  assign y_o = ~(a2_i & a1_i);

endmodule
