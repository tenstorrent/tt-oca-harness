// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Register d_i with an async active-low set to 1.
//
// Sample d_i on the rising edge of clk_i. Asserting set_ni low forces q_o high
// asynchronously.

module prim_dffsxq (
  input clk_i,       // Sampling clock.
  input d_i,         // Data input.
  input set_ni,      // Async active-low set; forces q_o to 1.
  output wire q_o    // Registered data.
);
  logic q_d;
  always_ff @(posedge clk_i or negedge set_ni) begin
    q_d <= ~set_ni ? 1'b1 : d_i;
  end

  assign q_o = q_d;

endmodule
