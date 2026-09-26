// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Reset Synchronizer
//
//--------------------------------------------------
module prim_sync_reset #(
  parameter int unsigned WIDTH = 16  // Reset width in clock cycles
) (
  input logic clk_i,
  input logic rst_ni,  // asynchronous reset input, active low
  input logic test_mode_i,  // test mode, active high
  input logic scan_rst_ni,  //scan reset to be used in test mode

  output logic sync_rst_no  // synchronized reset output, active low

);

  logic [WIDTH-1:0] sync_reg;

  prim_rst_mux2_hf_n u_sync_rst_n_bypass (
    .rst0_ni(sync_reg[WIDTH-1]),
    .rst1_ni(scan_rst_ni),
    .sel_i  (test_mode_i),
    .rst_no (sync_rst_no)
  );

  prim_metastab_hardened_dffr u_sync_dffr (
    .clk_i(clk_i),
    .rst_ni(rst_ni),       // Asynch Reset
    .d_i (1'b1),
    .q_o (sync_reg[0])
  );

  generate
    for (genvar stage = 1; stage < WIDTH; stage = stage + 1) begin : gen_rst_sync_stage

      prim_metastab_hardened_dffr u_sync_dffr (
        .clk_i(clk_i),
        .rst_ni(rst_ni),              // Asynch Reset
        .d_i (sync_reg[stage-1]),
        .q_o (sync_reg[stage])
      );

    end
  endgenerate


endmodule
