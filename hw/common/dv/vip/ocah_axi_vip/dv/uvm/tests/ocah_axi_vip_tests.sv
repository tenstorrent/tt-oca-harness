// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared-AXI-VIP selftest SV-UVM test include manifest. Tests are
// non-reusable by definition, so they are NOT packaged: this file is
// `include`d in module scope by dv/tb/tb_top.sv under `ifdef UVM and
// compiles as part of the top. One test class per file, named exactly like
// its cocotb twin (file = class = scenario name); this manifest only lists
// them so tb_top keeps a single stable hook as tests grow. Test classes
// stay thin — scenario content lives in ocah_axi_vip_seq_lib_pkg sequences;
// shared infrastructure lives in ocah_axi_vip_env_pkg.
//
// Testlist mapping: logical item names are framework-neutral scenario
// names; the `module` binding map's `uvm` entry equals the scenario name
// and drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import ocah_axi_vip_env_pkg::*;
import ocah_axi_vip_seq_lib_pkg::*;

`include "ocah_axi_vip_base_test.svh"
`include "ocah_axi_id_match_test.svh"
`include "ocah_axi_id_mismatch_test.svh"
`include "ocah_axi_pipeline_test.svh"
`include "ocah_axi_pipeline_missing_rlast_test.svh"
`include "ocah_axi_struct_bridge_test.svh"
