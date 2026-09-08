// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock NAND2 Gate
//
//--------------------------------------------------
module prim_clock_nand2 (
  input  i_A1,
  input  i_A2,
  output o_Y
);

  assign o_Y = ~(i_A2 & i_A1);

endmodule


