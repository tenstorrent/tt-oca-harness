// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare CPU-cluster sizing constants for the four-core SMC Rocket cluster.
//
// Defines core count and interrupt widths consumed by smc_4core_cpu and wrappers.
// Keeps these values aligned with the Chipyard DigitalTop configuration.

`ifndef SMC_4CORE_CPU_PACKAGE_DEFINED
`define SMC_4CORE_CPU_PACKAGE_DEFINED

package smc_4core_cpu_pkg;

  ////////////////////////////
  // CPU Control Parameters //
  ////////////////////////////

  localparam int unsigned NUM_CPU_CORES = 4;

  // Interrupt Parameters
  localparam bit [8:0] NUM_CPU_INTERRUPTS = 328;
  localparam bit [8:0] NUM_EXT_INTERRUPTS = 256;

  // in the four core config, the CPU cores are out of reset by default
  localparam cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t DEFAULT_RESET_SETTINGS = '{
      core0_reset_n_n0_scan: 1'b1,
      core1_reset_n_n0_scan: 1'b1,
      core2_reset_n_n0_scan: 1'b1,
      core3_reset_n_n0_scan: 1'b1,
      core0_reset_pulse_start_n0_scan: 1'b0,
      core1_reset_pulse_start_n0_scan: 1'b0,
      core2_reset_pulse_start_n0_scan: 1'b0,
      core3_reset_pulse_start_n0_scan: 1'b0,
      uncore_reset_n_n0_scan: 1'b1,
      _reserved_23_9: 15'd0,
      debug_reset_n_n0_scan: 1'b0,
      _reserved_63_25: 39'd0
  };

endpackage
`endif  // SMC_4CORE_CPU_PACKAGE_DEFINED
