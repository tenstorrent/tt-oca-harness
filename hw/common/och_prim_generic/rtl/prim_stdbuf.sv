// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard Buffer
//
//--------------------------------------------------
module prim_stdbuf #(
  parameter bit DONT_TOUCH = 1
) (
  input  a_i,
  output y_o
);

  assign y_o = a_i;
endmodule
