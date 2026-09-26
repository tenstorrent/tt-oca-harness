// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// NAND two inputs for clock-network use.
//
// Drive y_o with ~(a1_i & a2_i). Kept as a named cell so synthesis can map it to a clock-
// capable NAND2.

module prim_clock_nand2 (
  input  a1_i,  // First NAND input.
  input  a2_i,  // Second NAND input.
  output y_o    // NAND of a1_i and a2_i.
);
  assign y_o = ~(a2_i & a1_i);

endmodule
