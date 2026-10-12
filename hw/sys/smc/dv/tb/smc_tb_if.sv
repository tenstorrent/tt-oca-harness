// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC-local TB interface for the SV-UVM flow: wait-math clock periods,
// the test-sequenced power-good and reset pins, the reset-unit
// outputs and the fuse-sense / warm-domain release observables the
// sequences and the scoreboard read, the cold-reset assertion counter the
// scoreboard predictors re-baseline on, and the AXI SVA enable.
// Separate from the shared ocah_axi_if, which carries generic
// AXI pins only. Sequences, checkers, and the scoreboard reach DUT-local
// signals only through this interface. The cocotb realization exposes the
// same pins as tb_top ports driven from smc_base_test.

interface smc_tb_if;

  // Wait-math periods in nanoseconds. sys follows +pll_sys_period_ns; ref and periph are fixed.
  realtime ref_clk_period_ns    = 10.0;
  realtime smc_clk_period_ns    = 1.25;
  realtime periph_clk_period_ns = 5.0;

  // Driven by the TB (bring-up and reset scenarios owned by the test).
  // Initial values match the cocotb bring-up at time zero: power-good and
  // cold reset asserted, cool reset released.
  logic powergood  = 1'b0;
  logic rst_cold_n = 1'b0;
  logic rst_cool_n = 1'b1;

  // Reset-unit outputs (driven by the DUT top).
  logic powergood_stable;
  logic rst_cold_stable_ref_clk_n;
  logic rst_primary_ref_clk_n;
  logic rst_primary_smc_clk_n;
  logic rst_wdt_smc_clk_n;

  // CPU-cluster boundary state; cluster accesses wait for isolation to clear.
  logic cpu_cluster_isolate;

  // eFuse sense done and the warm-domain release it gates (driven by the
  // DUT top): warm-domain CSRs answer only after rst_warm_smc_clk_n rises.
  logic fuse_sense_done;
  logic fuse_reset_n;
  logic rst_warm_smc_clk_n;

  // Reset assertion counters (driven by tb_top). The CSR reference models
  // re-baseline their shadows on either, because both the cold reset and a
  // de-glitched cool reset are terms of the primary reset, which covers the
  // SMC "peripheral control and configuration paths" (clk_rst.adoc "Primary
  // and Warm Reset") -- every CSR block reached over SEP_IN.
  logic [31:0] cold_rst_assert_count;
  logic [31:0] cool_rst_assert_count;

  // Runtime enable for the shared AXI protocol SVA checker.
  logic axi_sva_en = 1'b1;

  // Runtime enable for the shared JTAG protocol SVA checker on the CPU TAP.
  logic jtag_sva_en = 1'b1;

endinterface : smc_tb_if
