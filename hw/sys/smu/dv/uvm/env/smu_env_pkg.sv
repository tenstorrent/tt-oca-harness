// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: bench constants, the two configuration
// levels, the virtual sequencer, the always-on scoreboard, and the
// environment that composes the shared JTAG VIP with the embedded DTP's own
// reference models and checkers (dtp_env_pkg, compiled ahead of this
// package). Compiles before smu_seq_lib_pkg, whose virtual sequences run on
// the smu_virtual_sequencer declared here.
//
// Include order is load-bearing: types first (every class reads them), then
// the cfgs (the env cfg derives from the test cfg), the virtual sequencer,
// the scoreboard, the env last.

`timescale 1ns / 1ps

package smu_env_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_jtag_uvm_pkg::*;
  import ocah_axi_uvm_pkg::*;  // the outbound SMN responder
  import dtp_env_pkg::*;  // the embedded DTP's reference models, checker, scoreboard

  `include "smu_types.svh"
  `include "smu_test_cfg.svh"
  `include "smu_env_cfg.svh"
  `include "smu_virtual_sequencer.svh"
  `include "smu_scoreboard.svh"
  `include "smu_env.svh"

endpackage : smu_env_pkg
