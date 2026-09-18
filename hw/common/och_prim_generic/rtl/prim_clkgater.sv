// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Gater
//
//--------------------------------------------------
module prim_clkgater (
  input clk_i,
  input en_i /*verilator clock_enable*/,
  input te_i,
  output clk_o
);

  logic latched_en;
  always_latch begin
    if (~clk_i) begin
      latched_en = en_i | te_i;
    end
  end
  assign clk_o = clk_i & latched_en;
endmodule
