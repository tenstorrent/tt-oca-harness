// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Stretch and synchronize an async active-low reset into clk_i.
//
// sync_rst_no asserts asynchronously with rst_ni and deasserts after WIDTH clk_i cycles of
// rst_ni deasserted. The first min(WIDTH, 4) stages are a prim_flop_*sync cell; each stage
// beyond 4 is a prim_metastab_hardened_dffr.
// test_mode_i, active-high, swaps scan_rst_ni onto the hazard-free bypass mux.
// sync_rst_no is the synchronized active-low reset output.

module prim_sync_reset #(
  parameter int unsigned WIDTH = 16  // Synchronizer stages, at least 2; clk_i cycles from rst_ni
                                     // deasserting to sync_rst_no deasserting.
) (
  input logic clk_i,  // Destination clock.
  input logic rst_ni,  // Async reset to synchronize, active-low.
  input logic test_mode_i,  // Test mode, active-high; selects scan_rst_ni.
  input logic scan_rst_ni,  // Scan reset used in test mode, active-low.

  output logic sync_rst_no  // Synchronized reset output, active-low.

);

  `include "ocah_assert.svh"

  localparam int unsigned SyncStages = (WIDTH < 4) ? WIDTH : 4;

  logic [WIDTH-1:SyncStages-1] sync_reg;

  `OCAH_ASSERT_STATIC(WidthCheck_A, WIDTH >= 2, "WIDTH must be at least 2")

  if (SyncStages == 2) begin : gen_sync
    prim_flop_2sync #(
      .Width(1),
      .EnablePrimCdcRand(0)
    ) u_sync (
      .clk_i (clk_i),
      .rst_ni(rst_ni),
      .d_i   (1'b1),
      .q_o   (sync_reg[SyncStages-1])
    );
  end else if (SyncStages == 3) begin : gen_sync
    prim_flop_3sync_r u_sync (
      .clk_i (clk_i),
      .d_i   (1'b1),
      .rst_ni(rst_ni),
      .q_o   (sync_reg[SyncStages-1])
    );
  end else begin : gen_sync
    prim_flop_4sync_r u_sync (
      .clk_i (clk_i),
      .d_i   (1'b1),
      .rst_ni(rst_ni),
      .q_o   (sync_reg[SyncStages-1])
    );
  end

  // The loop index names the stage, so gen_rst_sync_stage[WIDTH-1] is the last flop.
  for (genvar stage = SyncStages; stage < WIDTH; stage = stage + 1) begin : gen_rst_sync_stage
    prim_metastab_hardened_dffr u_sync_dffr (
      .clk_i (clk_i),
      .d_i   (sync_reg[stage-1]),
      .rst_ni(rst_ni),
      .q_o   (sync_reg[stage])
    );
  end

  prim_rst_mux2_hf_n u_sync_rst_n_bypass (
    .rst0_ni(sync_reg[WIDTH-1]),
    .rst1_ni(scan_rst_ni),
    .sel_i  (test_mode_i),
    .rst_no (sync_rst_no)
  );

endmodule
