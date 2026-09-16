// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// DFF SXQ Flop
//
//--------------------------------------------------
module prim_dffsxq (
  input i_CK,
  input i_D,
  input i_SN,
  output wire o_Q
);

  logic q_d;
  always_ff @(posedge i_CK or negedge i_SN) begin
    q_d <= ~i_SN ? 1'b1 : i_D;
  end

  assign o_Q = q_d;

endmodule


