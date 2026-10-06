// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// Two tiers, one readable flow per scenario:
//   * reusable operation sequences (`smc_<if>_<op>_seq`): one DUT operation
//     on one agent, built from the VIP sequence API, started by the scenario
//     layer on the virtual sequencer's handle for that agent (SEP_IN CSR
//     accesses on m_sep_in_seqr);
//   * scenario virtual sequences (`smc_<scenario>_test_seq`) on
//     smc_virtual_sequencer: smc_base_test_seq carries the operation
//     wrappers, the warm-domain release wait, the clock-domain waits, and
//     the per-pass named evidence; the concrete scenarios extend it and
//     never a VIP sequence.
// Pin-level driving lives in the VIP drivers; the always-on scoreboard lives
// in smc_env_pkg.
//
// Include order is load-bearing: operations first, then the base virtual
// sequence, then the scenarios.

`timescale 1ns / 1ps

package smc_seq_lib_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_axi_uvm_pkg::*;
  import smc_env_pkg::*;  // DUT types, cfgs, virtual sequencer

  // Reusable operations (one agent, one operation).
  `include "smc_axi_csr_write_seq.svh"
  `include "smc_axi_csr_read_seq.svh"
  `include "smc_axi_mem_write_seq.svh"
  `include "smc_axi_mem_read_seq.svh"

  // Scenario layer: the base virtual sequence, then the scenarios.
  `include "smc_base_test_seq.svh"
  `include "smc_register_sanity_test_seq.svh"
  `include "smc_default_reg_rd_test_seq.svh"
  `include "smc_reset_unit_lock_test_seq.svh"
  `include "smc_mutex_semaphore_test_seq.svh"
  `include "smc_spm_mem_boundary_test_seq.svh"
  `include "smc_multi_reset_csr_persistence_test_seq.svh"
  `include "smc_regblock_sparse_strobe_test_seq.svh"

endpackage : smc_seq_lib_pkg
