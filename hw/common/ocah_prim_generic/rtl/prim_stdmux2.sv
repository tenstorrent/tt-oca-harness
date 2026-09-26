// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Standard 2:1 Mux
//
//--------------------------------------------------
module prim_stdmux2 (
  input  i0_i,
  input  i1_i,
  input  sel_i,
  output y_o
);
  assign y_o = sel_i ? i1_i : i0_i;
endmodule
