// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU-local TB interface for the SV-UVM flow: wait-math clock periods,
// the test-sequenced power-good and cold-reset pins, the external
// boot-sequence gate, the reset-unit and fuse-sense observables the
// sequences read, the cold-reset assertion counter a reference model
// re-baselines on, and the JTAG SVA enable. Separate from the shared
// ocah_jtag_if (protocol pins only) and from dtp_tb_if, which the
// harness also instantiates for the embedded DTP so the DTP bench's own
// reference models and checkers attach unchanged. Sequences, checkers, and
// the scoreboard reach SMU-local signals only through this interface. The
// cocotb realization exposes the same pins as tb_top ports driven from
// smu_base_test.

interface smu_tb_if;

  // Wait-math periods in nanoseconds. sys follows +pll_sys_period_ns; ref and periph are fixed.
  realtime ref_clk_period_ns    = 10.0;
  realtime smu_clk_period_ns    = 1.25;
  realtime periph_clk_period_ns = 5.0;

  // Driven by the TB (bring-up and reset scenarios owned by the test).
  // Initial values match the cocotb bring-up at time zero: power-good and
  // cold reset asserted, the external boot-sequence gate released.
  logic powergood         = 1'b0;
  logic rst_cold_n        = 1'b0;
  logic ext_boot_seq_done = 1'b1;

  // Reset-unit outputs (driven by the DUT top).
  logic rst_cold_stable_ref_clk_n;
  logic rst_primary_ref_clk_n;
  logic rst_primary_smc_clk_n;
  logic rst_primary_periph_clk_n;

  // eFuse sense done and the delayed fuse reset it releases (driven by the
  // DUT top).
  logic fuse_sense_done;
  logic fuse_reset_n_delayed;

  // Lifecycle state (SEP=0 default posture; driven by the DUT top).
  logic [7:0] lc_state;

  // Cold-reset assertion counter (driven by tb_top).
  logic [31:0] cold_rst_assert_count;

  // Runtime enable for the shared JTAG protocol SVA checker.
  logic jtag_sva_en = 1'b1;

endinterface : smu_tb_if
