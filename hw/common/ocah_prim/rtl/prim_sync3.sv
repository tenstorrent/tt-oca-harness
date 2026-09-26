// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-stage Synchronizer
//
//--------------------------------------------------
module prim_sync3 #(
  parameter int unsigned WIDTH = 1
) (
  input  logic             clk_i,
  input  logic [WIDTH-1:0] d_i,
  output logic [WIDTH-1:0] q_o
);

  logic [WIDTH-1:0] d_del;

`ifdef SIMULATION
  // prim_cdc_rand_delay needs the first stage's output, which the synchronizer
  // cell does not expose.
  logic [WIDTH-1:0] first_stage_q;

  always_ff @(posedge clk_i) begin
    first_stage_q <= d_del;
  end

  prim_cdc_rand_delay #(
    .DataWidth(WIDTH)
  ) u_prim_cdc_rand_delay (
    .clk_i,
    .rst_ni     (1'b1),
    .src_data_i (d_i),
    .prev_data_i(first_stage_q),
    .dst_data_o (d_del)
  );
`else
  assign d_del = d_i;
`endif

  prim_flop_3sync u_sync3[WIDTH-1:0] (
    .clk_i (clk_i),
    .d_i   (d_del),
    .q_o   (q_o)
  );

endmodule
