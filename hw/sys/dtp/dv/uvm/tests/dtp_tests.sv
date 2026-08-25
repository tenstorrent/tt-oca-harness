// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM test include manifest. Tests are non-reusable by definition, so
// they are NOT packaged: this file is `include`d in module scope by
// tb/tb_top.sv under `ifdef UVM and compiles as part of the top. One test
// class per file, named exactly like its cocotb twin (file = class =
// scenario name); this manifest only lists them so tb_top keeps a single
// stable hook as tests grow. Test classes stay thin — scenario content lives
// in dtp_seq_lib_pkg sequences; shared infrastructure lives in dtp_env_pkg.
//
// Testlist mapping: logical item names are framework-neutral VPLAN scenario
// names; the `module` binding map's `uvm` entry equals the scenario name and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import dtp_env_pkg::*;
import dtp_seq_lib_pkg::*;

`include "dtp_base_test.svh"
`include "dtp_sanity_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_single_write_read_test.svh"
`include "dtp_jtag2axi_smc_axi_single_write_read_test.svh"
