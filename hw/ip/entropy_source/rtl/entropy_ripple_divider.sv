// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Divide an input clock through cascaded asynchronous toggle flip-flops.
//
// Each stage divides by two; div_o[0] is clk_i, div_o[1] is clk_i/2, through
// div_o[NUM_STAGES] = clk_i/2^NUM_STAGES. Stages use resettable D flops with inverted Q
// fed to D; the first stage clocks from clk_i and later stages from the prior Q.
//
// This asynchronous design intentionally violates synchronous rules and is only for
// sampler frequency division where those constraints are not critical.

module entropy_ripple_divider #(
  parameter int unsigned NUM_STAGES = 7  // Number of divide-by-2 stages.
) (
  input  logic                  rst_ni,  // Active-low asynchronous reset; clears every divider
                                         // stage.
  input  logic                  clk_i,  // Clock to divide.
  output logic [NUM_STAGES:0]   div_o   // Divided outputs [0]=clk_i, [1]=÷2, [2]=÷4, etc.
);

  // Internal signals for the ripple divider chain
  logic [NUM_STAGES-1:0] div_q;   // Q outputs from flip-flops
  logic [NUM_STAGES-1:0] div_qb;  // QB (inverted) outputs from flip-flops

  // Generate the ripple divider chain
  // Each stage is a toggle flip-flop (D=QB) that divides by 2
  for (genvar i = 0; i < NUM_STAGES; i++) begin : gen_div_stage
    if (i == 0) begin : gen_first_stage
      // First stage: clocked by input clock
      prim_flop u_div_ff (
        .clk_i (clk_i),
        .d_i  (div_qb[i]),
        .rst_ni (rst_ni),
        .q_o  (div_q[i])
      );
    end else begin : gen_ripple_stage
      // Subsequent stages: clocked by previous stage's Q output
      prim_flop u_div_ff (
        .clk_i (div_q[i-1]),
        .d_i  (div_qb[i]),
        .rst_ni (rst_ni),
        .q_o  (div_q[i])
      );
    end

    prim_inv u_div_inv (
      .in_i  (div_q[i]),
      .out_o (div_qb[i])
    );
  end

  // Output array: [0]=input clock, [1]=÷2, [2]=÷4, ..., [NUM_STAGES]=÷2^NUM_STAGES
  assign div_o = {div_q[NUM_STAGES-1:0], clk_i};

endmodule
