// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_ripple_divider.sv
 * @brief Asynchronous ripple frequency divider with cascaded toggle flip-flops.
 *
 * @details This module implements an asynchronous ripple frequency divider
 *          using cascaded toggle flip-flops. Each stage divides the frequency
 *          by 2, creating a chain of division factors. The divider uses gdffqb
 *          flip-flops configured as toggle flip-flops (D connected to QB).
 *          The first stage is clocked by the input clock, and each subsequent
 *          stage is clocked by the Q output of the previous stage. The output
 *          array provides all division factors simultaneously: div_o[0]=clk_i
 *          (divide by 1), div_o[1]=clk_i/2, div_o[2]=clk_i/4, ...,
 *          div_o[N]=clk_i/2^N. NOTE: This is an asynchronous design that
 *          intentionally violates synchronous design rules; it is used for
 *          frequency division where timing constraints are not critical.
 *
 * @param NUM_STAGES  Number of divide-by-2 stages. Default: 7
 */

module entropy_ripple_divider #(
  parameter int unsigned NUM_STAGES = 7  // Number of divide-by-2 stages
) (
  input  logic                  rst_ni,  // Async reset (active low)
  input  logic                  clk_i,   // Input clock to divide
  output logic [NUM_STAGES:0]   div_o    // Divided outputs [0]=clk_i, [1]=÷2, [2]=÷4, etc.
);

  // Internal signals for the ripple divider chain
  logic [NUM_STAGES-1:0] div_q;   // Q outputs from flip-flops
  logic [NUM_STAGES-1:0] div_qb;  // QB (inverted) outputs from flip-flops

  // Generate the ripple divider chain
  // Each stage is a toggle flip-flop (D=QB) that divides by 2
  generate
    for (genvar i = 0; i < NUM_STAGES; i++) begin : gen_div_stage
      if (i == 0) begin : gen_first_stage
        // First stage: clocked by input clock
        gdffqb u_div_ff (
          .d_i   (div_qb[i]),     // Toggle: D = QB
          .cdn_i (rst_ni),        // Async reset (active low)
          .cp_i  (clk_i),         // Clock from input
          .q_o   (div_q[i]),      // Q output
          .qb_o  (div_qb[i])      // QB output (inverted)
        );
      end else begin : gen_ripple_stage
        // Subsequent stages: clocked by previous stage's Q output
        gdffqb u_div_ff (
          .d_i   (div_qb[i]),     // Toggle: D = QB
          .cdn_i (rst_ni),        // Async reset (active low)
          .cp_i  (div_q[i-1]),    // Clock from previous stage
          .q_o   (div_q[i]),      // Q output
          .qb_o  (div_qb[i])      // QB output (inverted)
        );
      end
    end
  endgenerate

  // Output array: [0]=input clock, [1]=÷2, [2]=÷4, ..., [NUM_STAGES]=÷2^NUM_STAGES
  assign div_o = {div_q[NUM_STAGES-1:0], clk_i};

endmodule
