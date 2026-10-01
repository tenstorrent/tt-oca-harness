// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: DUT constants and codecs, the two
// configuration levels, the virtual sequencer, the expected items and the
// plain models, one reference model per scoreboard feature, the always-on
// scoreboard and subscribers, and the environment that composes the shared
// VIPs.
// Compiles before dtp_seq_lib_pkg, whose virtual sequences run on the
// dtp_virtual_sequencer declared here.
//
// Include order is load-bearing: types first (every class reads them), then
// the cfgs (the env cfg derives from the test cfg), the virtual sequencer,
// the expected items, the plain model classes, the reference models (they
// hold the models and publish the items), the subscribers and the
// scoreboard, the env last.

`timescale 1ns / 1ps

package dtp_env_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_jtag_uvm_pkg::*;
  import ocah_axi_uvm_pkg::*;
  // Generated cross-trigger network address map: the CSR windows behind the
  // XTRIG constants in dtp_types.svh.
  import cross_trigger_network_addrmap_pkg::*;

  // Generated register headers of the cross-trigger IP: field masks, shifts,
  // and reset values behind the XTRIG CSR constants in dtp_types.svh.
  `include "cross_trigger_port_reg.svh"
  `include "cross_trigger_matrix_reg.svh"
  `include "dtp_types.svh"
  `include "dtp_test_cfg.svh"
  `include "dtp_env_cfg.svh"
  `include "dtp_xtrig_ctp_shadow.svh"
  `include "dtp_virtual_sequencer.svh"

  // Expected items the reference models publish.
  `include "dtp_expected_item.svh"
  `include "dtp_jtag2axi_status_item.svh"

  // Plain models (no UVM parent): the PTAP instruction tracker, the XTRIG
  // CSR shadow, the JTAG2AXI bridges, iJTAG SIB gating, one downstream
  // STAP TAP, the PTAP 3DCR + STAP chain, the CTM routing OR.
  `include "dtp_jtag_ir_model.svh"
  `include "dtp_xtrig_csr_model.svh"
  `include "dtp_jtag2axi_model.svh"
  `include "dtp_ijtag_sib_model.svh"
  `include "dtp_stap_ds_state.svh"
  `include "dtp_stap_3dcr_model.svh"
  `include "dtp_xtrig_ctm_model.svh"

  // One reference model per scoreboard feature.
  `include "dtp_ir_decode_ref_model.svh"
  `include "dtp_idcode_ref_model.svh"
  `include "dtp_bypass_ref_model.svh"
  `include "dtp_xtrig_csr_ref_model.svh"
  `include "dtp_xtrig_decode_ref_model.svh"
  `include "dtp_jtag2axi_req_ref_model.svh"
  `include "dtp_jtag2axi_status_ref_model.svh"

  `include "dtp_tap_fsm_checker.svh"
  `include "dtp_jtag_scan_builder.svh"
  `include "dtp_scan_window_monitor.svh"
  `include "dtp_axi_port_history.svh"
  `include "dtp_scoreboard.svh"
  `include "dtp_env.svh"

endpackage : dtp_env_pkg
