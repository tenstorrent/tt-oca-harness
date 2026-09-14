// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// Two tiers, one readable flow per scenario:
//   * reusable operation sequences (`smu_jtag_<op>_seq`): one operation on
//     the embedded DTP's primary TAP agent, built from the VIP sequence API,
//     started by the scenario layer on the virtual sequencer's JTAG handle;
//   * scenario virtual sequences (`smu_<scenario>_test_seq`) on
//     smu_virtual_sequencer: smu_base_test_seq carries the operation
//     wrappers, the TAP-state checks, the bounded waits, the reset controls,
//     and the per-pass named evidence; the concrete scenarios extend it and
//     never a VIP sequence.
// Pin-level driving lives in the VIP driver; the always-on scoreboard and
// the embedded DTP's reference models live in smu_env_pkg.
//
// Include order is load-bearing: the operation base, the operations, then
// the base virtual sequence, then the scenarios.

`timescale 1ns / 1ps

package smu_seq_lib_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_jtag_uvm_pkg::*;
  import smu_env_pkg::*;  // bench constants, cfgs, virtual sequencer

  // Reusable operations (one agent, one operation).
  `include "smu_jtag_op_seq.svh"
  `include "smu_jtag_tap_reset_seq.svh"
  `include "smu_jtag_trst_seq.svh"
  `include "smu_jtag_tms_walk_seq.svh"
  `include "smu_jtag_goto_state_seq.svh"
  `include "smu_jtag_ir_scan_seq.svh"
  `include "smu_jtag_dr_scan_seq.svh"

  // Scenario layer: the base virtual sequence, then the scenarios.
  `include "smu_base_test_seq.svh"
  `include "smu_dtp_jtag_smoke_test_seq.svh"

endpackage : smu_seq_lib_pkg
