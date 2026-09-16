// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-Flop Synchronizer
//
//--------------------------------------------------
module prim_flop_3sync (
  input i_CK,
  input i_D,
  output wire o_Q
);

  logic q_d, q_dd, q_ddd;

  always_ff @(posedge i_CK) begin
    q_d   <= i_D;
    q_dd  <= q_d;
    q_ddd <= q_dd;
  end

  assign o_Q = q_ddd;
endmodule

