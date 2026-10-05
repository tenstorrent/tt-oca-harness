// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP SV-UVM test include manifest. Tests are non-reusable by definition, so
// they are NOT packaged: this file is `include`d in module scope by
// tb/tb_top.sv under `ifdef UVM and compiles as part of the top. One test
// class per file, named exactly like its cocotb twin (file = class =
// scenario name); this manifest only lists them so tb_top keeps a single
// stable hook as tests grow. Test classes stay thin — scenario content lives
// in sep_seq_lib_pkg sequences; shared infrastructure lives in sep_env_pkg.
//
// Testlist mapping: logical item names are framework-neutral VPLAN scenario
// names; the `module` binding map's `uvm` entry equals the scenario name and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import ocah_lib_pkg::*;  // ocah_test base and the ocah_sequence hook type
import sep_env_pkg::*;
import sep_seq_lib_pkg::*;

`include "sep_base_test.svh"

// CSR scenarios on the CPU-LSU AXI4 splice.
`include "sep_axi_smoke_test.svh"
`include "sep_address_map_test.svh"

// Memory and bus-error scenarios on the CPU-LSU AXI4 splice.
`include "sep_sram_smoke_test.svh"
`include "sep_periph_bus_err_misaligned_test.svh"

// Reset-path scenario driven and observed through sep_tb_if.
`include "sep_clock_uvm_wdt_rst_input_reset_path_test.svh"
// Interrupt and OTBN memory scenarios on the CPU-LSU AXI4 splice.
`include "sep_irq_ip_to_aggregator_test.svh"
`include "sep_otbn_mem_smoke_test.svh"
// eFuse sense scenario, observed through sep_tb_if with no AXI access.
`include "sep_efuse_sense_test.svh"

// Key Manager memory scenario (KM ROM image, tb_top KM probes).
`include "sep_km_mem_smoke_test.svh"

// Adopter overlay hook: an external (non-OSS) build may append vendor-
// specific test classes -- e.g. a commercial-VIP overlay -- by defining
// SEP_OVERLAY_TESTS to the quoted name of an include file on its own
// include path. Never defined by the OSS flists.
`ifdef SEP_OVERLAY_TESTS
`include `SEP_OVERLAY_TESTS
`endif
