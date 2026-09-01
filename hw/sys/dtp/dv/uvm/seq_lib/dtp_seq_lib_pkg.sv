// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// dtp_jtag_base_test_seq issues ocah_jtag_item transactions on the shared
// ocah_jtag_vip agent's sequencer (the SV analogue of the cocotb
// dtp_jtag_base_test_seq): TAP reset, IR/DR scans, raw TMS walks, DTP-local
// reset sequencing, scan-path checks, and the BYPASS latency check.
// dtp_jtag_cmd_lib_seq layers the instruction-family evidence helpers on
// top (per-pass ocah_jtag_checker, bypass/loopback/decoded-IR/TMP-status
// checks, scan-builder cross-checks); the basic-JTAG scenario sequences
// extend it. dtp_jtag2axi_base_test_seq carries the bridge helper layer
// (single/series ops, responder backdoor, error arming); the JTAG2AXI
// scenario sequences extend it. Pin-level driving lives in the VIP driver;
// per-cycle FSM legality and closure live in the env's dtp_tap_fsm_checker.

`timescale 1ns/1ps

package dtp_seq_lib_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    import ocah_jtag_uvm_pkg::*;
    import ocah_axi_uvm_pkg::*;   // shared AXI cfg/evidence handles
    import jtag_tap_pkg::*;       // DUT one-hot tap_state_e for scan-path checks
    import jtag_inst_reg_pkg::*;

    `include "dtp_jtag_base_test_seq.svh"
    `include "dtp_jtag_cmd_lib_seq.svh"

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
    `include "dtp_jtag2axi_single_op_seq.svh"
    `include "dtp_jtag2axi_smc_axi_wr_test_seq.svh"
    `include "dtp_jtag2axi_smc_axi_rd_test_seq.svh"
    `include "dtp_jtag2axi_error_test_seq.svh"
    `include "dtp_jtag2axi_otp_axi_test_seq.svh"
    `include "dtp_jtag2axi_robustness_test_seq.svh"

    // Debug-TDR scenarios (TMP / IC_RESET / DEBUG_CONTROL / CAPS).
    `include "dtp_debug_tdr_base_test_seq.svh"
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
    `include "dtp_scan_ref_model.svh"
    `include "dtp_scan_base_test_seq.svh"
    `include "dtp_ijtag_scan_test_seq.svh"
    `include "dtp_stap_scan_test_seq.svh"
    `include "dtp_dbg_disable_scan_matrix_test_seq.svh"
    `include "dtp_dbg_disable_jtag2axi_matrix_test_seq.svh"

endpackage : dtp_seq_lib_pkg
