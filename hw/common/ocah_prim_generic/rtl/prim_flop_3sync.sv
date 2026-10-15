// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 3 flops.
//
// Chain 3 positive-edge flops so q_o is d_i delayed by three clk_i cycles. The chain has
// no reset, so q_o is undefined until three clk_i edges after power-up.

`include "ocah_registers.svh"

module prim_flop_3sync (
  input clk_i,       // Destination-domain clock.
  input d_i,         // Async data to synchronize.
  output wire q_o    // Synchronized data.
);
  logic q_d, q_dd, q_ddd;

  `OCAH_FFNR(q_d, d_i, clk_i)
  `OCAH_FFNR(q_dd, q_d, clk_i)
  `OCAH_FFNR(q_ddd, q_dd, clk_i)

  assign q_o = q_ddd;
endmodule
