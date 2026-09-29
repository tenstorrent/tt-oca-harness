// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: DUT constants and CSR lane helpers, the
// two configuration levels, the virtual sequencer, the reference models the
// scoreboard pairs against, the always-on scoreboard, and the environment
// that composes the shared AXI VIP. Compiles before
// smc_seq_lib_pkg, whose virtual sequences run on the smc_virtual_sequencer
// declared here.
//
// Include order is load-bearing: types first (every class reads them), then
// the cfgs (the env cfg derives from the test cfg), the virtual sequencer,
// the reference models, the scoreboard, the env last.

`timescale 1ns / 1ps

package smc_env_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_axi_uvm_pkg::*;

  `include "smc_types.svh"
  `include "smc_test_cfg.svh"
  `include "smc_env_cfg.svh"
  `include "smc_virtual_sequencer.svh"
  `include "smc_scratch_csr_ref_model.svh"
  `include "smc_default_reg_ref_model.svh"
  `include "smc_lock_csr_ref_model.svh"
  `include "smc_mutex_sema_ref_model.svh"
  `include "smc_spm_mem_ref_model.svh"
  `include "smc_regblock_wide_ref_model.svh"
  `include "smc_scoreboard.svh"
  `include "smc_env.svh"

endpackage : smc_env_pkg
