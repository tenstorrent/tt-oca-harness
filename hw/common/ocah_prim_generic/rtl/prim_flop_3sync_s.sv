// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 3 flops, with q_o async-set to 1.
//
// Invert d_i, pass it through 3 flops that clear to 0 when set_ni is low, then reinvert so q_o is 1
// during and after async set and follows d_i three clk_i cycles later. Use this when the idle or
// reset value of the destination signal must be high.

`include "ocah_registers.svh"

module prim_flop_3sync_s (
  input clk_i,       // Destination-domain clock.
  d_i,               // Async data to synchronize.
  set_ni,            // Async active-low set; forces q_o to 1.
  output wire q_o    // Synchronized data.
);
  logic q_d_inv, q_dd_inv, q_ddd_inv;
  logic D_inv;
  assign D_inv = ~d_i;
  `OCAH_FF(q_d_inv, D_inv, 1'b0, clk_i, set_ni)
  `OCAH_FF(q_dd_inv, q_d_inv, 1'b0, clk_i, set_ni)
  `OCAH_FF(q_ddd_inv, q_dd_inv, 1'b0, clk_i, set_ni)
  assign q_o = ~q_ddd_inv;

endmodule
