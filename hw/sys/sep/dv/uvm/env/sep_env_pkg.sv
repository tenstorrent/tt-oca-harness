// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: DUT constants, the generated register
// header, and CSR lane helpers, the two configuration levels, the virtual
// sequencer, the reference models the scoreboard pairs against, the
// always-on scoreboard, and the environment that composes the shared AXI
// VIP. Compiles before sep_seq_lib_pkg, whose virtual sequences run on the
// sep_virtual_sequencer declared here.
//
// Include order is load-bearing: types first (every class reads them), then
// the cfgs (the env cfg derives from the test cfg), the virtual sequencer,
// the reference models, the scoreboard, the env last.

`timescale 1ns / 1ps

package sep_env_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_axi_uvm_pkg::*;

  `include "sep_types.svh"
  `include "sep_test_cfg.svh"
  `include "sep_env_cfg.svh"
  `include "sep_virtual_sequencer.svh"
  `include "sep_cpu_ctrl_csr_ref_model.svh"
  `include "sep_scoreboard.svh"
  `include "sep_env.svh"

endpackage : sep_env_pkg
