// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard 2:1 Mux
//
//--------------------------------------------------
module prim_stdmux2 (
  input  i_I0,
  input  i_I1,
  input  i_SEL,
  output o_Y
);
  assign o_Y = i_SEL ? i_I1 : i_I0;
endmodule
