// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Buffer a_i onto y_o.
//
// Drive y_o with a_i. DONT_TOUCH asks synthesis not to dissolve the cell.

module prim_stdbuf #(
  parameter bit DONT_TOUCH = 1  // Keep this cell through synthesis optimization.
) (
  input  a_i,  // Buffer input.
  output y_o   // Buffered a_i.
);
  assign y_o = a_i;
endmodule
