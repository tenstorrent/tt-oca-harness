// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU-local TB interface for the SV-UVM flow: the harness clock periods and
// two clock mirrors, the test-sequenced power-good, cold-reset, boot-gate
// and GPIO boot-stall pins, the reset-unit, fuse-sense, lifecycle and DTP
// debug-control observables the sequences, monitors and reference models
// read, the cold-reset assertion counter, and the JTAG SVA enable. Separate
// from the shared ocah_jtag_if (protocol pins only) and from dtp_tb_if,
// which the harness also instantiates for the embedded DTP so the DTP
// bench's own reference models and checkers attach unchanged. Sequences,
// checkers, and the scoreboard reach SMU-local signals only through this
// interface. The cocotb realization exposes the same pins as
// smu_wrapper_uvm_top ports driven from smu_base_test.

interface smu_tb_if;

  // Clock periods the harness generators read, set by the env from
  // smu_env_cfg (the test cfg randomizes them from the runner seed).
  int unsigned ref_clk_period_ns     = 10;
  int unsigned smu_clk_period_ns     = 10;
  int unsigned periph_clk_period_ns  = 20;
  int unsigned sep_wdt_clk_period_ns = 100;

  // Clock mirrors for the monitors and the cycle-bounded waits.
  logic clk_smu;
  logic clk_ref;

  // Driven by the TB (bring-up and reset scenarios owned by the test).
  // Initial values match the cocotb bring-up at time zero: power-good and
  // cold reset asserted, the external boot-sequence gate released, the GPIO
  // boot-stall pad idle.
  logic powergood             = 1'b0;
  logic rst_cold_n            = 1'b0;
  logic ext_boot_seq_done     = 1'b1;
  logic gpio_boot_stall_drive = 1'b0;

  // Reset-unit outputs (driven by the DUT top).
  logic rst_cold_stable_ref_clk_n;
  logic rst_primary_ref_clk_n;
  logic rst_primary_smc_clk_n;
  logic rst_primary_periph_clk_n;

  // eFuse sense done and the delayed fuse reset it releases (driven by the
  // DUT top).
  logic fuse_sense_done;
  logic fuse_reset_n_delayed;

  // Lifecycle state broadcast at the SMU boundary (driven by the DUT top).
  logic [7:0] lc_state;

  // DTP debug-control exports as the SMC receives them.
  logic jtag_boot_stall;
  logic jtag_boot_stall_ovrd;
  logic jtag_ic_reset_ext_ovrd;
  logic jtag_ic_reset_ext_ctrl_n;
  logic jtag_ic_reset_smc_ovrd;
  logic jtag_ic_reset_smc_ctrl_n;
  // The whole SMC IC_RESET slice as the SMC reset controller sees it.
  smc_pkg::jtag_smc_reset_ctrl_ovrd_t smc_reset_ctrl_ovrd;
  smc_pkg::jtag_smc_reset_ctrl_val_t  smc_reset_ctrl_val;
  // Lifecycle gate of the SMC-fabric JTAG2AXI bridge (1 = disabled).
  logic smc_jtag2axi_security_disable;
  // DTP clock-stop aggregate toward the PLL gaters.
  logic dtp_stop_clks;

  // Cold-reset assertion counter (driven by the harness).
  logic [31:0] cold_rst_assert_count;

  // Runtime enable for the shared JTAG protocol SVA checker.
  logic jtag_sva_en = 1'b1;

endinterface : smu_tb_if
