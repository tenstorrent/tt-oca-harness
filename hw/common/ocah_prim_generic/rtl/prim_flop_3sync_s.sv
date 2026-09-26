// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 3 flops that async-set to 1.
//
// Invert d_i, pass it through 3 flops that clear to 0 when set_ni is low, then reinvert
// so q_o comes out of async set as 1. Use this when the idle or reset value of the
// destination signal must be high.

module prim_flop_3sync_s (
  input clk_i,       // Destination-domain clock.
  d_i,
  set_ni,
  output wire q_o    // Synchronized data.
);
  logic q_d_inv, q_dd_inv, q_ddd_inv;
  logic D_inv;
  assign D_inv = ~d_i;
  always_ff @(posedge clk_i or negedge set_ni) begin
    if (set_ni == 1'b0) begin
      q_d_inv <= 1'b0;
      q_dd_inv <= 1'b0;
      q_ddd_inv <= 1'b0;
    end else begin
      q_d_inv <= D_inv;
      q_dd_inv <= q_d_inv;
      q_ddd_inv <= q_dd_inv;
    end
  end
  assign q_o = ~q_ddd_inv;

endmodule
