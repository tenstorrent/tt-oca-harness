// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize d_i into the clk_i domain through 2 flops.
//
// Optionally insert prim_sync_randomized_delay ahead of the flops when
// RANDOM_DELAY_GRAY_CODE selects shared delay.
// Use prim_flop_2sync with its internal CDC randomizer disabled so only one random-delay
// model is on the path.
// There is no reset; q_o follows d_i after two clk_i edges.

module prim_sync2 #(
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

  // Unlike prim_flop_3sync/4sync, prim_flop_2sync is the OpenTitan cell: OT port names and a
  // Width parameter, so it takes the vector directly rather than an array of 1-bit instances.
  // EnablePrimCdcRand must stay 0 -- prim_sync_randomized_delay above already models the CDC
  // delay, and OT's internal prim_cdc_rand_delay would stack a second random delay on the path.
  prim_flop_2sync #(
    .Width            (WIDTH),
    .EnablePrimCdcRand(1'b0)
  ) u_sync2 (
    .clk_i (clk_i),
    .rst_ni(1'b1),      // non-resettable variant; use prim_sync2r when a reset is needed
    .d_i   (d_del),
    .q_o   (q_o)
  );

endmodule
