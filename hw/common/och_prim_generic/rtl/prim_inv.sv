// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Invert in_i onto out_o.
//
// Drive out_o with ~in_i. DONT_TOUCH asks synthesis not to dissolve the cell.

module prim_inv #(
  parameter bit DONT_TOUCH = 1  // Keep this cell through synthesis optimization.
) (
  input  in_i,  // Value to invert.
  output out_o  // Inverted in_i.
);
  assign out_o = ~in_i;
endmodule


