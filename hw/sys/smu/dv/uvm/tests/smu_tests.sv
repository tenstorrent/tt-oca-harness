// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SV-UVM test include manifest. Tests are non-reusable by definition, so
// they are NOT packaged: this file is `include`d in module scope by
// tb/tb_top.sv under `ifdef UVM and compiles as part of the top. One test
// class per file, named exactly like its cocotb twin (file = class =
// scenario name); this manifest only lists them so tb_top keeps a single
// stable hook as tests grow. Test classes stay thin — scenario content lives
// in smu_seq_lib_pkg sequences; shared infrastructure lives in smu_env_pkg.
//
// Testlist mapping: logical item names are framework-neutral VPLAN scenario
// names; the `module` binding map's `uvm` entry equals the scenario name and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import ocah_lib_pkg::*;  // ocah_test base and the ocah_sequence hook type
import smu_env_pkg::*;
import smu_seq_lib_pkg::*;

`include "smu_base_test.svh"

// DTP scenarios on the primary TAP of the embedded DTP.
`include "smu_dtp_jtag_smoke_test.svh"

// Adopter overlay hook: an external (non-OSS) build may append vendor-
// specific test classes -- e.g. a commercial-VIP overlay -- by defining
// SMU_OVERLAY_TESTS to the quoted name of an include file on its own
// include path. Never defined by the OSS flists.
`ifdef SMU_OVERLAY_TESTS
`include `SMU_OVERLAY_TESTS
`endif
