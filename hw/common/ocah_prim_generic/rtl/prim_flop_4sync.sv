// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 4 flops.
//
// Chain 4 positive-edge flops so q_o is d_i delayed by four clk_i cycles. The chain has
// no reset, so q_o is undefined until four clk_i edges after power-up.

`include "ocah_registers.svh"

module prim_flop_4sync (
  input clk_i,       // Destination-domain clock.
  input d_i,         // Async data to synchronize.
  output wire q_o    // Synchronized data.
);
  logic q_d, q_dd, q_ddd, q_dddd;

  `OCAH_FFNR(q_d, d_i, clk_i)
  `OCAH_FFNR(q_dd, q_d, clk_i)
  `OCAH_FFNR(q_ddd, q_dd, clk_i)
  `OCAH_FFNR(q_dddd, q_ddd, clk_i)

  assign q_o = q_dddd;
endmodule
