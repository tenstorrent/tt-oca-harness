// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Latch one bit while the active-low gate is low.
//
// Maps to one sg13g2_dllrq_1 with its reset tied inactive.
module prim_latch_n (
  input  logic d_i,  // Value to latch.
  input  logic g_ni,  // Active-low gate; the latch is transparent while it is low.
  output logic q_o  // Latched value.
);
  (* dont_touch = "true" *)
  sg13g2_dllrq_1 u_cell (
    .D       (d_i),
    .GATE_N  (g_ni),
    .RESET_B (1'b1),
    .Q       (q_o)
  );
endmodule
