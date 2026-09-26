// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 4 flops.
//
// Chain 4 positive-edge flops so q_o is a metastability-hardened copy of d_i. The chain
// has no reset and powers up undefined until d_i is sampled.

module prim_flop_4sync (
  input clk_i,       // Destination-domain clock.
  input d_i,         // Async data to synchronize.
  output wire q_o    // Synchronized data.
);
  logic q_d, q_dd, q_ddd, q_dddd;

  always_ff @(posedge clk_i) begin
    q_d    <= d_i;
    q_dd   <= q_d;
    q_ddd  <= q_dd;
    q_dddd <= q_ddd;
  end

  assign q_o = q_dddd;
endmodule
