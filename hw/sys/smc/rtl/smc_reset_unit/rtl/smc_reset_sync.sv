// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-------------------------------------------------
// SMC Reset Sync
//
//-------------------------------------------------

module smc_reset_sync (

  input  logic                                   clk_smc_i,
  input  logic                                   clk_ref_i,
  input  logic                                   clk_periph_i,

  input  logic                                   rst_cold_stable_ni,
  input  logic                                   rst_primary_ni,
  input  logic                                   rst_warm_ni,
  input  logic                                   rst_wdt_ni,

  output logic                                   rst_cold_smc_no,
  output logic                                   rst_primary_smc_clk_no,
  output logic                                   rst_warm_smc_clk_no,
  output logic                                   rst_wdt_smc_clk_no,

  output logic                                   rst_cold_ref_clk_no,
  output logic                                   rst_primary_ref_clk_no,
  output logic                                   rst_primary_periph_clk_no,

  input  logic                                   test_en_i,
  input  logic                                   scan_rst_ni
);

  // Cold reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_cold_smc_sync (
    .clk                    (clk_smc_i),
    .rst_n                  (rst_cold_stable_ni),
    .sync_rst_n             (rst_cold_smc_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );

  // Primary reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_primary_smc_sync (
    .clk                    (clk_smc_i),
    .rst_n                  (rst_primary_ni),
    .sync_rst_n             (rst_primary_smc_clk_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );

  // Core reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_warm_smc_sync (
    .clk                    (clk_smc_i),
    .rst_n                  (rst_warm_ni),
    .sync_rst_n             (rst_warm_smc_clk_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );

  // WDT reset synchronization to SMC clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_wdt_smc_sync (
    .clk                    (clk_smc_i),
    .rst_n                  (rst_wdt_ni),
    .sync_rst_n             (rst_wdt_smc_clk_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );


  // Cold reset synchronization to Reference clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_cold_ref_clk_sync (
    .clk                    (clk_ref_i),
    .rst_n                  (rst_cold_stable_ni),
    .sync_rst_n             (rst_cold_ref_clk_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );

  // Primary reset synchronization to Reference clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_primary_ref_clk_sync (
    .clk                    (clk_ref_i),
    .rst_n                  (rst_primary_ni),
    .sync_rst_n             (rst_primary_ref_clk_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );

  // Primary reset synchronization to Peripheral clock
  prim_sync_reset #(
    .WIDTH(4)
  ) u_rst_primary_periph_clk_sync (
    .clk                    (clk_periph_i),
    .rst_n                  (rst_primary_ni),
    .sync_rst_n             (rst_primary_periph_clk_no),

    .test_mode              (test_en_i),
    .scan_rst_n             (scan_rst_ni)
  );

endmodule
