// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// NAND two inputs for clock-network use.
//
// Drive y_o with ~(a1_i & a2_i). A synthesis build replaces this behavioural model with a
// clock-capable technology NAND2 cell of the same name and ports.

module prim_clock_nand2 (
  input  a1_i,  // First NAND input.
  input  a2_i,  // Second NAND input.
  output y_o    // NAND of a1_i and a2_i.
);
  assign y_o = ~(a2_i & a1_i);

endmodule
