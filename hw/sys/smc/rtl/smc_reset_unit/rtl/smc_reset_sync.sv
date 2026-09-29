// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize SMC resets into the SMC, reference, and peripheral clocks.
//
// Produces async-assert / sync-deassert resets for each SMC clock via prim_sync_reset.
// Fans synchronized cold, primary, warm, and WDT resets out to the SMC, reference, and
// peripheral domains.

module smc_reset_sync (

  input  logic                                   clk_smc_i,  // SMC core clock; destination of the
                                                             // cold, primary, warm and WDT
                                                             // synchronizers.
  input  logic                                   clk_ref_i,  // Reference clock; destination of the
                                                             // cold and primary synchronizers.
  input  logic                                   clk_periph_i,  // Peripheral clock; destination of
                                                                // the primary synchronizer.

  input  logic                                   rst_cold_stable_ni,  // De-glitched and extended cold reset from
                                                                      // the reset controller, active-low.
  input  logic                                   rst_primary_ni,  // Primary reset from the reset
                                                                  // controller, active-low and
                                                                  // asynchronous.
  input  logic                                   rst_warm_ni,  // Warm reset after the JTAG
                                                               // override, active-low and
                                                               // asynchronous.
  input  logic                                   rst_wdt_ni,  // Watchdog reset from the reset
                                                              // controller, active-low and
                                                              // asynchronous.

  output logic                                   rst_cold_smc_no,  // Stable cold reset, active-low,
                                                                   // with deassertion synchronized
                                                                   // to the SMC core clock.
  output logic                                   rst_primary_smc_clk_no,  // Primary reset, active-low, with
                                                                          // deassertion synchronized to the SMC core
                                                                          // clock.
  output logic                                   rst_warm_smc_clk_no,  // Warm reset, active-low, with deassertion
                                                                       // synchronized to the SMC core clock.
  output logic                                   rst_wdt_smc_clk_no,  // Watchdog reset, active-low, with
                                                                      // deassertion synchronized to the SMC core
                                                                      // clock.

  output logic                                   rst_cold_ref_clk_no,  // Stable cold reset, active-low, with
                                                                       // deassertion synchronized to the reference
                                                                       // clock.
  output logic                                   rst_primary_ref_clk_no,  // Primary reset, active-low, with
                                                                          // deassertion synchronized to the reference
                                                                          // clock.
  output logic                                   rst_primary_periph_clk_no,  // Primary reset, active-low, with
                                                                             // deassertion synchronized to the peripheral
                                                                             // clock.

  input  logic                                   test_en_i,  // Scan test mode enable, active-high;
                                                             // selects scan_rst_ni in place of
                                                             // every reset this module generates.
  input  logic                                   scan_rst_ni  // Scan reset, active-low, that
                                                              // replaces the generated resets while
                                                              // test_en_i is high.
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
