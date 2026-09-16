// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Active-Low Latch
//
//--------------------------------------------------
module prim_latch_n (
  input  i_D,
  input  i_Gn,
  output o_Q
);
  logic Q_int;
  always_latch begin : capture_strap
    if (!i_Gn) begin
      Q_int <= i_D;
    end
  end
  assign o_Q = Q_int;

endmodule
