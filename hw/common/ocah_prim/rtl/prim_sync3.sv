// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize each bit of d_i into clk_i through a three-flop chain.
//
// Each bit uses its own prim_flop_3sync cell. Under SIMULATION, prim_cdc_rand_delay
// randomizes when a change on d_i reaches the first stage to model CDC uncertainty;
// synthesis connects d_i to the cells directly.

`include "ocah_registers.svh"

module prim_sync3 #(
  parameter int unsigned WIDTH = 1  // Number of independent bits synchronized.
) (
  input  logic             clk_i,   // Destination clock.
  input  logic [WIDTH-1:0] d_i,     // Asynchronous bits, each resolved independently.
  output logic [WIDTH-1:0] q_o      // Synchronized bits in the clk_i domain.
);

  logic [WIDTH-1:0] d_del;

`ifdef EMULATION
  assign d_del = d_i;
`elsif SIMULATION
  // prim_cdc_rand_delay needs the first stage's output, which the synchronizer
  // cell does not expose.
  logic [WIDTH-1:0] first_stage_q;

  `OCAH_FFNR(first_stage_q, d_del, clk_i)

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
