// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 3 flops.
//
// Chain 3 positive-edge flops so q_o is d_i delayed by three clk_i cycles. Async
// active-low rst_ni clears the chain to 0.

`include "ocah_registers.svh"

module prim_flop_3sync_r (
  input clk_i,       // Destination-domain clock.
  input d_i,         // Async data to synchronize.
  input rst_ni,      // Async active-low reset; clears q_o to 0.
  output wire q_o    // Synchronized data.
);
  logic q_d, q_dd, q_ddd;

  `OCAH_FF(q_d, d_i, 1'b0, clk_i, rst_ni)
  `OCAH_FF(q_dd, q_d, 1'b0, clk_i, rst_ni)
  `OCAH_FF(q_ddd, q_dd, 1'b0, clk_i, rst_ni)

  assign q_o = q_ddd;

endmodule
