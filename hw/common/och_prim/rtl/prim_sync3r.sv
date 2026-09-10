// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-stage Resettable Synchronizer
//
//--------------------------------------------------
module prim_sync3r #(
  parameter int unsigned WIDTH = 1,
  parameter bit RANDOM_DELAY_GRAY_CODE = 1'b0
) (
  input  logic             i_clk,
  input  logic [WIDTH-1:0] i_d,
  input  logic             i_reset_n,
  output logic [WIDTH-1:0] o_q
);

`ifndef SYNTHESIS
  wire [WIDTH-1:0] d_del;

  prim_sync_randomized_delay #(
    .WIDTH             (WIDTH),
    .RANDOM_DELAY_RESET(1),
    .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
  ) rand_del (
    .i_clk(i_clk),  // input                   Clock
    .i_d(i_d),  // input    [WIDTH-1:0]    Input Data
    .i_reset_n           (i_reset_n  ), // input                   Active Low Reset, if synchronizer is not resettable tie to 1
    .i_mux_sel_ovr       ({WIDTH*2{1'b0}}), // input    [WIDTH*2-1:0]  Mux Select Override Value, NOT USED FOR NOW

    .o_mux_sel(),      // output   [WIDTH*2-1:0]  Output Mux Select, NOT USED FOR NOW
    .o_d_del  (d_del)  // output   [WIDTH-1:0]    Delayed Data
  );
`else
  wire [WIDTH-1:0] d_del;
  assign d_del = i_d;
`endif

  prim_flop_3sync_r sync3r[WIDTH-1:0] (
    .clk_i(i_clk),
    .rst_ni(i_reset_n),
    .d_i (d_del),
    .q_o (o_q)
  );

endmodule




