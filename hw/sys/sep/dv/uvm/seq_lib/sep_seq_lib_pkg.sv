// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// Two tiers, one readable flow per scenario:
//   * reusable operation sequences (`sep_<if>_<op>_seq`): one DUT operation
//     on one agent, built from the VIP sequence API, started by the scenario
//     layer on the virtual sequencer's handle for that agent (CPU-LSU CSR
//     accesses on m_lsu_seqr);
//   * scenario virtual sequences (`sep_<scenario>_test_seq`) on
//     sep_virtual_sequencer: sep_base_test_seq carries the operation
//     wrappers, the fuse-sense-done wait, the system-clock waits, and the
//     per-pass named evidence; the concrete scenarios extend it and never a
//     VIP sequence.
// Pin-level driving lives in the VIP drivers; the always-on scoreboard lives
// in sep_env_pkg.
//
// Include order is load-bearing: operations first, then the base virtual
// sequence, then the scenarios.

`timescale 1ns / 1ps

package sep_seq_lib_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_axi_uvm_pkg::*;
  import sep_env_pkg::*;  // DUT types, cfgs, virtual sequencer

  // Reusable operations (one agent, one operation).
  `include "sep_axi_csr_write_seq.svh"
  `include "sep_axi_csr_read_seq.svh"
  `include "sep_axi_bus_write_seq.svh"
  `include "sep_axi_bus_read_seq.svh"

  // Scenario layer: the base virtual sequence, then the scenarios.
  `include "sep_base_test_seq.svh"
  `include "sep_axi_smoke_test_seq.svh"
  `include "sep_sram_smoke_test_seq.svh"
  `include "sep_address_map_test_seq.svh"

endpackage : sep_seq_lib_pkg
