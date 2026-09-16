// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// Two tiers, one readable flow per scenario:
//   * reusable operation sequences (`dtp_<if>_<op>_seq`): one DUT operation
//     on one agent, built from the VIP sequence API, started by the scenario
//     layer on the virtual sequencer's handle for that agent (JTAG operations
//     on m_jtag_seqr, XTRIG CSR accesses on m_xtrig_seqr);
//   * scenario virtual sequences (`dtp_<scenario>_test_seq`) on
//     dtp_virtual_sequencer: dtp_base_test_seq carries the operation
//     wrappers, the TAP-state tracking, the DTP-local checks, and the
//     system-domain helpers; the family layers (basic JTAG, JTAG2AXI, debug
//     TDR, scan network, cross-trigger) add their evidence helpers; the
//     concrete scenarios extend a family layer and never a VIP sequence.
// Pin-level driving lives in the VIP drivers; per-cycle FSM legality, scan
// reconstruction, and the always-on scoreboard live in dtp_env_pkg.
//
// Include order is load-bearing: operations first, then the base virtual
// sequence, then each family base before its scenarios.

`timescale 1ns / 1ps

package dtp_seq_lib_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_checker_uvm_pkg::*;  // protocol-neutral named-evidence base
  import ocah_lib_pkg::*;  // shared framework bases, knobs, rng
  import ocah_jtag_uvm_pkg::*;
  import ocah_axi_uvm_pkg::*;  // shared AXI cfg/evidence handles
  import jtag_tap_pkg::*;  // DUT one-hot tap_state_e for scan-path checks
  import jtag_inst_reg_pkg::*;
  import dtp_env_pkg::*;  // DUT types, cfgs, virtual sequencer, models

  // Reusable operations (one agent, one operation).
  `include "dtp_jtag_op_seq.svh"
  `include "dtp_jtag_tap_reset_seq.svh"
  `include "dtp_jtag_tms_walk_seq.svh"
  `include "dtp_jtag_goto_state_seq.svh"
  `include "dtp_jtag_ir_scan_seq.svh"
  `include "dtp_jtag_dr_scan_seq.svh"
  `include "dtp_jtag_read_tdr_seq.svh"
  `include "dtp_jtag_write_tdr_seq.svh"
  `include "dtp_jtag2axi_single_op_seq.svh"
  `include "dtp_jtag2axi_single_status_seq.svh"
  `include "dtp_jtag2axi_series_ctrl_seq.svh"
  `include "dtp_jtag2axi_series_data_seq.svh"
  `include "dtp_axi_csr_write_seq.svh"
  `include "dtp_axi_csr_read_seq.svh"

  // Scenario layer: base virtual sequence, the basic-JTAG family, and the
  // debug-TDR family; the reset-family and undefined-instruction scenarios
  // read the debug-TDR pins through the latter.
  `include "dtp_base_test_seq.svh"
  `include "dtp_jtag_base_test_seq.svh"
  `include "dtp_debug_tdr_base_test_seq.svh"

  // Basic-JTAG instruction-family scenarios.
  `include "dtp_jtag_bypass_test_seq.svh"
  `include "dtp_jtag_inv_bypass_test_seq.svh"
  `include "dtp_jtag_zero_length_bypass_test_seq.svh"
  `include "dtp_jtag_idcode_test_seq.svh"
  `include "dtp_jtag_undef_instr_test_seq.svh"
  `include "dtp_jtag_runbist_test_seq.svh"
  `include "dtp_jtag_sample_preload_test_seq.svh"
  `include "dtp_jtag_extest_test_seq.svh"
  `include "dtp_jtag_intest_test_seq.svh"
  `include "dtp_jtag_clamp_test_seq.svh"
  `include "dtp_jtag_clamp_hold_test_seq.svh"
  `include "dtp_jtag_clamp_release_test_seq.svh"
  `include "dtp_jtag_highz_test_seq.svh"
  `include "dtp_jtag_ac_extest_train_test_seq.svh"
  `include "dtp_jtag_ac_extest_pulse_test_seq.svh"
  `include "dtp_jtag_trst_test_seq.svh"
  `include "dtp_jtag_trst_por_independence_test_seq.svh"
  `include "dtp_jtag_tlr_reset_test_seq.svh"

  `include "dtp_sanity_test_seq.svh"

  // JTAG2AXI bridge scenarios.
  `include "dtp_jtag2axi_base_test_seq.svh"
  `include "dtp_jtag2axi_single_write_read_test_seq.svh"
  `include "dtp_jtag2axi_smc_axi_wr_test_seq.svh"
  `include "dtp_jtag2axi_smc_axi_rd_test_seq.svh"
  `include "dtp_jtag2axi_error_test_seq.svh"
  `include "dtp_jtag2axi_otp_axi_test_seq.svh"
  `include "dtp_jtag2axi_robustness_test_seq.svh"

  // Debug-TDR scenarios (TMP / IC_RESET / DEBUG_CONTROL / CAPS).
  `include "dtp_jtag_tmp_status_register_smoke_test_seq.svh"
  `include "dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq.svh"
  `include "dtp_jtag_tmp_status_bypass_escape_test_seq.svh"
  `include "dtp_jtag_ic_reset_test_seq.svh"
  `include "dtp_dbg_jtag_caps_test_seq.svh"
  `include "dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq.svh"
  `include "dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq.svh"
  `include "dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq.svh"
  `include "dtp_dbg_ctrl_boot_stall_test_seq.svh"
  `include "dtp_dbg_smc_jtag2axi_caps_test_seq.svh"
  `include "dtp_dbg_smc_otp_jtag2axi_caps_test_seq.svh"
  `include "dtp_dbg_sep_otp_jtag2axi_caps_test_seq.svh"

  // Scan-network scenarios (iJTAG SIBs / STAP 3DCR / dbg_disable matrices).
  `include "dtp_scan_base_test_seq.svh"
  `include "dtp_ijtag_scan_test_seq.svh"
  `include "dtp_stap_scan_test_seq.svh"
  `include "dtp_dbg_disable_scan_matrix_test_seq.svh"
  `include "dtp_dbg_disable_jtag2axi_matrix_test_seq.svh"

  // Cross-trigger scenarios (XTRIG CSR / CTP protocols / CTM routing).
  `include "dtp_xtrig_base_test_seq.svh"
  `include "dtp_xtrig_csr_test_seq.svh"
  `include "dtp_xtrig_route_test_seq.svh"
  `include "dtp_ctm_route_test_seq.svh"

endpackage : dtp_seq_lib_pkg
