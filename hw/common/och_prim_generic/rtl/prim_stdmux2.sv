// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard 2:1 Mux
//
//--------------------------------------------------
module prim_stdmux2 #(
  parameter int Width = 1
) (
  input  [Width-1:0]  i_I0,
  input  [Width-1:0]  i_I1,
  input              i_SEL,
  output [Width-1:0]   o_Y
);
  assign o_Y = i_SEL ? i_I1 : i_I0;
endmodule


