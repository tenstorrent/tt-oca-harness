// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Gater
//
//--------------------------------------------------
module prim_clkgater (
  input i_clk,
  input i_en /*verilator clock_enable*/,
  input i_te,
  output o_clk
);

  logic latched_en;
  always_latch begin
    if (~i_clk) begin
      latched_en = i_en | i_te;
    end
  end
  assign o_clk = i_clk & latched_en;
endmodule
