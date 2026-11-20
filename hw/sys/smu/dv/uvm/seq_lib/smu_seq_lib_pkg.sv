// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// Two tiers, one readable flow per scenario:
//   * reusable operation sequences: the embedded DTP's own (`dtp_jtag_<op>_seq`,
//     from dtp_seq_lib_pkg), each one operation on the primary TAP agent,
//     started by the scenario layer on the virtual sequencer's JTAG handle;
//   * scenario virtual sequences (`smu_<scenario>_test_seq`) on
//     smu_virtual_sequencer: smu_base_test_seq carries the operation
//     wrappers, the TDR and JTAG2AXI accesses, the TAP-state checks, the
//     bounded waits, the reset and pin controls, and the per-pass named
//     evidence; the concrete scenarios extend it and never a VIP sequence.
// Pin-level driving lives in the VIP driver; the always-on scoreboard, the
// SMU-level reference models and the embedded DTP's reference models live in
// smu_env_pkg.
//
// Include order is load-bearing: the base virtual sequence, then the
// scenarios.

`timescale 1ns / 1ps

package smu_seq_lib_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_jtag_uvm_pkg::*;
  import smu_env_pkg::*;  // bench constants, cfgs, scoreboard, virtual sequencer
  import dtp_seq_lib_pkg::*;  // reusable JTAG operation sequences

  // Scenario layer: the base virtual sequence, then the scenarios.
  `include "smu_base_test_seq.svh"
  `include "smu_dtp_jtag_smoke_test_seq.svh"
  `include "smu_jtag_reset_override_test_seq.svh"
  `include "smu_smc_dtp_jtag2axi_smoke_test_seq.svh"
  `include "smu_smc_mailbox_sanity_test_seq.svh"
  `include "smu_smc_wdt_sanity_test_seq.svh"
  `include "smu_smc_wdt_timeout_irq_test_seq.svh"
  `include "smu_boot_stall_jtag_cold_reset_matrix_test_seq.svh"
  `include "smu_ext_boot_seq_gate_test_seq.svh"

endpackage : smu_seq_lib_pkg
