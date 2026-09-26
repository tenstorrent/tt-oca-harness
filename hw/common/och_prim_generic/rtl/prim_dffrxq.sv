// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Register d_i with an async active-low reset to 0.
//
// Sample d_i on the rising edge of clk_i. Asserting rst_ni low clears q_o asynchronously.

module prim_dffrxq (
  input clk_i,       // Sampling clock.
  input d_i,         // Data input.
  input rst_ni,      // Async active-low reset; clears q_o to 0.
  output wire q_o    // Registered data.
);
  logic q_d;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (rst_ni == 1'b0) begin
      q_d <= 1'b0;
    end else begin
      q_d <= d_i;
    end
  end

  assign q_o = q_d;

endmodule
