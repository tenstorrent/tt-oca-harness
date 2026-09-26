// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 3 flops.
//
// Optionally insert randomized delay ahead of the flops; RANDOM_DELAY_GRAY_CODE shares one
// delay select across bits.
// There is no reset; q_o follows d_i after three clk_i edges.

module prim_sync3 #(
  parameter int unsigned WIDTH = 1,  // Datapath width.
  parameter bit RANDOM_DELAY_GRAY_CODE = 1'b0  // Shares one random delay select across bits when set.
) (
  input  logic             clk_i,  // Destination clock.
  input  logic [WIDTH-1:0] d_i,  // Async data to synchronize.
  output logic [WIDTH-1:0] q_o  // Synchronized data.
);

`ifndef SYNTHESIS
  wire [WIDTH-1:0] d_del;

  prim_sync_randomized_delay #(
    .WIDTH                 (WIDTH),
    .RANDOM_DELAY_RESET    (0),
    .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
  ) u_rand_del (
    .clk_i        (clk_i),            // input                   Clock
    .d_i          (d_i),              // input    [WIDTH-1:0]    Input Data
    .rst_ni       (1'b1),             // input                   Active Low Reset, if synchronizer is not resettable tie to 1
    .mux_sel_ovr_i({WIDTH*2{1'b0}}),  // input    [WIDTH*2-1:0]  Mux Select Override Value, NOT USED FOR NOW

    .mux_sel_o    (),                 // output   [WIDTH*2-1:0]  Output Mux Select, NOT USED FOR NOW
    .d_del_o      (d_del)             // output   [WIDTH-1:0]    Delayed Data
  );
`else
  wire [WIDTH-1:0] d_del;
  assign d_del = d_i;
`endif

  prim_flop_3sync u_sync3[WIDTH-1:0] (
    .clk_i(clk_i),
    .d_i  (d_del),
    .q_o  (q_o)
  );

endmodule
