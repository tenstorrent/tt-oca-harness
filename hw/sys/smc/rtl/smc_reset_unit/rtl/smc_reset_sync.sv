// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize SMC resets into the SMC, reference, and peripheral clocks.
//
// Produces async-assert / sync-deassert resets for each SMC clock via prim_sync_reset.
// Fans synchronized cold, primary, warm, and WDT resets out to the SMC, reference, and
// peripheral domains.

module smc_reset_sync (

  input  logic                                   clk_smc_i,  // Smc clock.
  input  logic                                   clk_ref_i,  // Ref clock.
  input  logic                                   clk_periph_i,  // Periph clock.

  input  logic                                   rst_cold_stable_ni,  // Rst cold stable.
  input  logic                                   rst_primary_ni,  // Rst primary.
  input  logic                                   rst_warm_ni,  // Rst warm.
  input  logic                                   rst_wdt_ni,  // Rst wdt.

  output logic                                   rst_cold_smc_no,  // Rst cold smc.
  output logic                                   rst_primary_smc_clk_no,  // Rst primary smc clk.
  output logic                                   rst_warm_smc_clk_no,  // Rst warm smc clk.
  output logic                                   rst_wdt_smc_clk_no,  // Rst wdt smc clk.

  output logic                                   rst_cold_ref_clk_no,  // Rst cold ref clk.
  output logic                                   rst_primary_ref_clk_no,  // Rst primary ref clk.
  output logic                                   rst_primary_periph_clk_no,  // Rst primary periph
                                                                             // clk.

  input  logic                                   test_en_i,  // Test en.
  input  logic                                   scan_rst_ni  // Scan rst.
);

  // Cold reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_cold_smc_sync (
    .clk_i                    (clk_smc_i),
    .rst_ni                   (rst_cold_stable_ni),
    .sync_rst_no              (rst_cold_smc_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );

  // Primary reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_primary_smc_sync (
    .clk_i                    (clk_smc_i),
    .rst_ni                   (rst_primary_ni),
    .sync_rst_no              (rst_primary_smc_clk_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );

  // Core reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_warm_smc_sync (
    .clk_i                    (clk_smc_i),
    .rst_ni                   (rst_warm_ni),
    .sync_rst_no              (rst_warm_smc_clk_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );

  // WDT reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_wdt_smc_sync (
    .clk_i                    (clk_smc_i),
    .rst_ni                   (rst_wdt_ni),
    .sync_rst_no              (rst_wdt_smc_clk_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );


  // Cold reset synchronization to Reference clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_cold_ref_clk_sync (
    .clk_i                    (clk_ref_i),
    .rst_ni                   (rst_cold_stable_ni),
    .sync_rst_no              (rst_cold_ref_clk_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );

  // Primary reset synchronization to Reference clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_primary_ref_clk_sync (
    .clk_i                    (clk_ref_i),
    .rst_ni                   (rst_primary_ni),
    .sync_rst_no              (rst_primary_ref_clk_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );

  // Primary reset synchronization to Peripheral clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_primary_periph_clk_sync (
    .clk_i                    (clk_periph_i),
    .rst_ni                   (rst_primary_ni),
    .sync_rst_no              (rst_primary_periph_clk_no),

    .test_mode_i              (test_en_i),
    .scan_rst_ni              (scan_rst_ni)
  );

endmodule
