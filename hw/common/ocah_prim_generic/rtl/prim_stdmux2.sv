// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Select between i0_i and i1_i onto y_o.
//
// Drive y_o with i1_i when sel_i is high and i0_i when sel_i is low.

module prim_stdmux2 (
  input  i0_i,   // Data selected when sel_i is low.
  input  i1_i,   // Data selected when sel_i is high.
  input  sel_i,  // Selects i1_i when high, i0_i when low.
  output y_o     // Muxed data.
);
  assign y_o = sel_i ? i1_i : i0_i;
endmodule
