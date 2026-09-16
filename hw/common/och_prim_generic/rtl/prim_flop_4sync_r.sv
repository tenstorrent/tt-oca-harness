// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-Flop Synchronizer (Reset)
//
//--------------------------------------------------
module prim_flop_4sync_r (
  input i_CK,
  input i_D,
  input i_RN,
  output wire o_Q
);

  logic q_d, q_dd, q_ddd, q_dddd;
  always_ff @(posedge i_CK or negedge i_RN) begin
    if (i_RN == 1'b0) begin
      q_d <= 1'b0;
      q_dd <= 1'b0;
      q_ddd <= 1'b0;
      q_dddd <= 1'b0;
    end else begin
      q_d <= i_D;
      q_dd <= q_d;
      q_ddd <= q_dd;
      q_dddd <= q_ddd;
    end
  end
  assign o_Q = q_dddd;

endmodule

