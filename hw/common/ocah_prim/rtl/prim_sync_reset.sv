// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Stretch and synchronize an async active-low reset into clk_i.
//
// WIDTH is the minimum asserted length in clk_i cycles after rst_ni deasserts.
// test_mode_i, active-high, swaps scan_rst_ni onto the bypass mux.
// sync_rst_no is the synchronized active-low reset output.

module prim_sync_reset #(
  parameter int unsigned WIDTH = 16  // Minimum reset hold in clk_i cycles.
) (
  input logic clk_i,  // Destination clock.
  input logic rst_ni,  // Async reset to synchronize, active-low.
  input logic test_mode_i,  // Test mode, active-high; selects scan_rst_ni.
  input logic scan_rst_ni,  // Scan reset used in test mode, active-low.

  output logic sync_rst_no  // Synchronized reset output, active-low.

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
