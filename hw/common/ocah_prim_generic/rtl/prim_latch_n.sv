// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Latch d_i while g_ni is low.
//
// Pass d_i through to q_o while g_ni is low and hold the last value while g_ni is high.

module prim_latch_n (
  input  d_i,   // Data passed to q_o while the latch is open.
  input  g_ni,  // Active-low gate; open when low.
  output q_o    // Latched data.
);
  logic Q_int;
  always_latch begin : capture_strap
    if (!g_ni) begin
      Q_int <= d_i;
    end
  end
  assign q_o = Q_int;

endmodule
