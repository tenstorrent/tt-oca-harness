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
  input  logic             clk_i,
  input  logic [WIDTH-1:0] d_i,
  input  logic             rst_ni,
  output logic [WIDTH-1:0] q_o
);

`ifndef SYNTHESIS
  wire [WIDTH-1:0] d_del;

  prim_sync_randomized_delay #(
    .WIDTH             (WIDTH),
    .RANDOM_DELAY_RESET(1),
    .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
  ) u_rand_del (
    .clk_i        (clk_i),            // input                   Clock
    .d_i          (d_i),              // input    [WIDTH-1:0]    Input Data
    .rst_ni       (rst_ni),           // input                   Active Low Reset, if synchronizer is not resettable tie to 1
    .mux_sel_ovr_i({WIDTH*2{1'b0}}),  // input    [WIDTH*2-1:0]  Mux Select Override Value, NOT USED FOR NOW

    .mux_sel_o    (),                 // output   [WIDTH*2-1:0]  Output Mux Select, NOT USED FOR NOW
    .d_del_o      (d_del)             // output   [WIDTH-1:0]    Delayed Data
  );
`else
  wire [WIDTH-1:0] d_del;
  assign d_del = d_i;
`endif

  prim_flop_3sync_r u_sync3r[WIDTH-1:0] (
    .clk_i (clk_i),
    .rst_ni(rst_ni),
    .d_i   (d_del),
    .q_o   (q_o)
  );

endmodule
