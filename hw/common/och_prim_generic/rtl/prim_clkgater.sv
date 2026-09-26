// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Gate clk_i with a latch-based enable.
//
// Sample en_i | te_i while clk_i is low and AND that latched enable with clk_i to produce
// clk_o. te_i forces the clock through for test.

module prim_clkgater (
  input clk_i,                            // Clock to gate.
  input en_i /*verilator clock_enable*/,  // Functional clock enable.
  input te_i,                             // Test enable; forces the clock through.
  output clk_o                            // Gated clock.
);
  logic latched_en;
  always_latch begin
    if (~clk_i) begin
      latched_en = en_i | te_i;
    end
  end
  assign clk_o = clk_i & latched_en;
endmodule
