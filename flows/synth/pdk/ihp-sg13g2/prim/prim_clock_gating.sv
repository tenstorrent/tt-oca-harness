// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Gate a clock with a glitch-free latch-based clock gate.
//
// Maps to one sg13g2_slgcp_1, whose scan enable takes test_en_i. clk_o runs while en_i or
// test_en_i is high when clk_i is low.
module prim_clock_gating #(
  parameter bit NoFpgaGate    = 1'b0,  // FPGA gate bypass; unused by the cell.
  parameter bit FpgaBufGlobal = 1'b1  // FPGA global buffer select; unused by the cell.
) (
  input  logic clk_i,  // Clock to gate.
  input  logic en_i,  // Functional enable.
  input  logic test_en_i,  // Test enable; forces the clock on.
  output logic clk_o  // Gated clock.
);
  (* dont_touch = "true" *)
  sg13g2_slgcp_1 u_cell (
    .CLK     (clk_i),
    .GATE    (en_i),
    .SCE     (test_en_i),
    .GCLK    (clk_o)
  );
endmodule
