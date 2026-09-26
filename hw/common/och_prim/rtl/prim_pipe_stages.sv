// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Chain NUM_STAGES enabled pipeline registers of WIDTH bits.
//
// en_i qualifies every stage; when low, hold q_o.
// rst_ni clears all stages asynchronously.
// NUM_STAGES of zero collapses to a wire from d_i to q_o.

module prim_pipe_stages #(
  parameter int unsigned WIDTH      = 8,  // Datapath width.
  parameter int unsigned NUM_STAGES = 1  // Number of register stages.
) (
  input  logic               clk_i,  // Pipeline clock.
  input  logic               rst_ni,  // Async reset, active-low.
  input  logic               en_i,  // Clock-enable for every stage.
  input  logic   [WIDTH-1:0] d_i,  // Pipeline input.

  output logic   [WIDTH-1:0] q_o  // Pipeline output after NUM_STAGES.
);

  logic [WIDTH-1:0] stage_data[0:NUM_STAGES];

  assign stage_data[0] = d_i;

  genvar i;
  for (i = 0; i < NUM_STAGES; i = i + 1) begin : gen_pipe_stages

    prim_pipe_stage #(
      .WIDTH(WIDTH)
    ) u_prim_pipe_stage (
      .clk_i      ( clk_i           ),
      .rst_ni     ( rst_ni          ),
      .en_i       ( en_i            ),
      .d_i        ( stage_data[i]   ),
      .q_o        ( stage_data[i+1] )
    );

  end

  assign q_o = stage_data[NUM_STAGES];

endmodule



module prim_pipe_stage #(
  parameter int unsigned WIDTH = 8
) (
  input logic clk_i,
  input logic rst_ni,
  input logic en_i,
  input logic [WIDTH-1:0] d_i,

  output logic [WIDTH-1:0] q_o
);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      q_o <= WIDTH'(0);
    end else if (en_i) begin
      q_o <= d_i;
    end
  end

endmodule
