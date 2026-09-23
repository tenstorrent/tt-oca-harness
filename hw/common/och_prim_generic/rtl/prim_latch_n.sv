// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Active-Low Latch
//
//--------------------------------------------------
module prim_latch_n (
  input  d_i,
  input  g_ni,
  output q_o
);
  logic Q_int;
  always_latch begin : capture_strap
    if (!g_ni) begin
      Q_int <= d_i;
    end
  end
  assign q_o = Q_int;

endmodule
