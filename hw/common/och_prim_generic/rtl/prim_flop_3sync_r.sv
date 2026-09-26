// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 3 flops.
//
// Chain 3 positive-edge flops so q_o is a metastability-hardened copy of d_i. Async
// active-low rst_ni clears the chain to 0.

module prim_flop_3sync_r (
  input clk_i,       // Destination-domain clock.
  input d_i,         // Async data to synchronize.
  input rst_ni,      // Async active-low reset; clears q_o to 0.
  output wire q_o    // Synchronized data.
);
  logic q_d, q_dd, q_ddd;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (rst_ni == 1'b0) begin
      q_d   <= 1'b0;
      q_dd  <= 1'b0;
      q_ddd <= 1'b0;
    end else begin
      q_d   <= d_i;
      q_dd  <= q_d;
      q_ddd <= q_dd;
    end
  end

  assign q_o = q_ddd;

endmodule
