// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared-AXI-VIP selftest sequence library (`<DUT>_seq_lib_pkg` convention).
//
// Scenario sequences extend the VIP's ocah_axi_master_sequence and drive the
// master ONLY through its blocking result operations; slave-side fault
// controls and backdoor access go through the bound ocah_axi_slave_sequence.
// Named CHK-* evidence lands on the env-owned scenario checker.

`timescale 1ns / 1ps

package ocah_axi_vip_seq_lib_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_axi_uvm_pkg::*;

  `include "ocah_axi_id_match_test_seq.svh"
  `include "ocah_axi_id_mismatch_test_seq.svh"
  `include "ocah_axi_pipeline_reject_catcher.svh"
  `include "ocah_axi_pipeline_test_seq.svh"
  `include "ocah_axi_struct_bridge_test_seq.svh"

endpackage : ocah_axi_vip_seq_lib_pkg
