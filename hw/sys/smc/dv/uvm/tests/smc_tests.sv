// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC SV-UVM test include manifest. Test classes are not wrapped in a
// package: tb/tb_top.sv `include`s this file in module scope under `ifdef UVM,
// so it compiles as part of the top. One test class per file, named exactly
// like its cocotb twin (file = class = scenario name); tb_top includes only
// this manifest. Test classes stay thin: scenario content lives in
// smc_seq_lib_pkg sequences and shared infrastructure in smc_env_pkg.
//
// Testlist mapping: logical item names are framework-neutral VPLAN scenario
// names; the `module` binding map's `uvm` entry equals the scenario name and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import ocah_lib_pkg::*;  // ocah_test base and the ocah_sequence hook type
import smc_env_pkg::*;
import smc_seq_lib_pkg::*;

`include "smc_base_test.svh"

// CSR scenarios on the SEP_IN AXI4 ingress.
`include "smc_register_sanity_test.svh"
`include "smc_default_reg_rd_test.svh"
`include "smc_regblock_sparse_strobe_test.svh"

// Reset-unit write-once lock scenarios.
`include "smc_reset_unit_lock_test.svh"

// CPU_CTRL side-effect register scenarios.
`include "smc_mutex_semaphore_test.svh"

// SPM memory datapath scenarios (full-width 64-bit accesses).
`include "smc_spm_mem_boundary_test.svh"

// Reset-domain scenarios (test-sequenced resets through smc_tb_if).
`include "smc_multi_reset_csr_persistence_test.svh"

// Adopter overlay hook: an external (non-OSS) build may append vendor-
// specific test classes -- e.g. a commercial-VIP overlay -- by defining
// SMC_OVERLAY_TESTS to the quoted name of an include file on its own
// include path. Never defined by the OSS flists.
`ifdef SMC_OVERLAY_TESTS
`include `SMC_OVERLAY_TESTS
`endif
