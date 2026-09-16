// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 4-Flop Synchronizer (Set)
//
//--------------------------------------------------
module prim_flop_4sync_s (
  input i_CK,
  i_D,
  i_SN,
  output wire o_Q
);

  logic q_d_inv, q_dd_inv, q_ddd_inv, q_dddd_inv;
  logic D_inv;
  assign D_inv = ~i_D;
  always_ff @(posedge i_CK or negedge i_SN) begin
    if (i_SN == 1'b0) begin
      q_d_inv <= 1'b0;
      q_dd_inv <= 1'b0;
      q_ddd_inv <= 1'b0;
      q_dddd_inv <= 1'b0;
    end else begin
      q_d_inv <= D_inv;
      q_dd_inv <= q_d_inv;
      q_ddd_inv <= q_dd_inv;
      q_dddd_inv <= q_ddd_inv;
    end
  end
  assign o_Q = ~q_dddd_inv;

endmodule


