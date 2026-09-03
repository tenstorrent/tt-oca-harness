// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard Buffer
//
//--------------------------------------------------
module prim_stdbuf #(
  parameter bit DONT_TOUCH = 1
) (
  input  i_A,
  output o_Y
);

  assign o_Y = i_A;
endmodule
