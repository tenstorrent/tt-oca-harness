// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Metastability-Hardened DFFR
//
//--------------------------------------------------
module prim_metastab_hardened_dffr (
  input i_CK,
  input i_D,
  input i_RN,
  output wire o_Q
);
  logic q_d;
  always_ff @(posedge i_CK or negedge i_RN) begin
    if (i_RN == 1'b0) begin
      q_d <= 1'b0;
    end else begin
      q_d <= i_D;
    end
  end
  assign o_Q = q_d;
endmodule

