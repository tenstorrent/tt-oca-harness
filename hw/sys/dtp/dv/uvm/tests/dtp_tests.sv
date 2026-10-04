// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM test include manifest, `include`d in module scope by
// tb/tb_top.sv under `ifdef UVM; the tests compile as part of the top and
// are not packaged. One test class per file, named exactly like its cocotb
// twin (file = class = scenario name). Test classes stay thin — scenario
// content lives in dtp_seq_lib_pkg sequences; shared infrastructure lives in
// dtp_env_pkg.
//
// Testlist mapping: logical item names are framework-neutral VPLAN scenario
// names; the `module` binding map's `uvm` entry equals the scenario name and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import ocah_lib_pkg::*;  // ocah_test base and the ocah_sequence hook type
import dtp_env_pkg::*;
import dtp_seq_lib_pkg::*;

`include "dtp_base_test.svh"
`include "dtp_sanity_test.svh"

// Basic-JTAG instruction-family scenarios.
`include "dtp_jtag_bypass_test.svh"
`include "dtp_jtag_inv_bypass_test.svh"
`include "dtp_jtag_zero_length_bypass_test.svh"
`include "dtp_jtag_idcode_test.svh"
`include "dtp_jtag_undef_instr_test.svh"
`include "dtp_jtag_runbist_test.svh"
`include "dtp_jtag_sample_preload_test.svh"
`include "dtp_jtag_extest_test.svh"
`include "dtp_jtag_intest_test.svh"
`include "dtp_jtag_clamp_test.svh"
`include "dtp_jtag_clamp_hold_test.svh"
`include "dtp_jtag_clamp_release_test.svh"
`include "dtp_jtag_highz_test.svh"
`include "dtp_jtag_ac_extest_train_test.svh"
`include "dtp_jtag_ac_extest_pulse_test.svh"
`include "dtp_jtag_trst_test.svh"
`include "dtp_jtag_trst_por_independence_test.svh"
`include "dtp_jtag_tlr_reset_test.svh"

// JTAG2AXI single-op scenarios.
`include "dtp_jtag2axi_smc_otp_axi_single_write_read_test.svh"
`include "dtp_jtag2axi_smc_axi_single_write_read_test.svh"

// SMC-fabric JTAG2AXI scenarios.
`include "dtp_jtag2axi_smc_axi_single_write_test.svh"
`include "dtp_jtag2axi_smc_axi_single_write_data_verify_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_incr_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_incr_narrow_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_no_incr_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_incr_with_error_test.svh"
`include "dtp_jtag2axi_smc_axi_random_ops_test.svh"
`include "dtp_jtag2axi_smc_axi_write_security_gating_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_read_incr_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_read_incr_narrow_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_read_no_incr_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_read_incr_with_error_test.svh"
`include "dtp_jtag2axi_smc_axi_read_random_ops_test.svh"
`include "dtp_jtag2axi_smc_axi_read_security_gating_test.svh"
`include "dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test.svh"
`include "dtp_jtag2axi_smc_axi_error_single_write_test.svh"
`include "dtp_jtag2axi_smc_axi_error_single_read_test.svh"
`include "dtp_jtag2axi_smc_axi_error_series_no_incr_write_test.svh"
`include "dtp_jtag2axi_smc_axi_error_series_no_incr_read_test.svh"
`include "dtp_jtag2axi_smc_axi_error_series_incr_write_test.svh"
`include "dtp_jtag2axi_smc_axi_error_series_incr_read_test.svh"
`include "dtp_jtag2axi_smc_axi_error_series_incr_write_with_status_test.svh"
`include "dtp_jtag2axi_smc_axi_error_series_incr_read_with_status_test.svh"
`include "dtp_jtag2axi_smc_axi_error_security_gating_test.svh"

// SMC OTP JTAG2AXI scenarios.
`include "dtp_jtag2axi_smc_otp_axi_single_write_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_single_write_data_verify_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_incr_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_no_incr_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_random_ops_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_write_security_gating_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_read_incr_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_read_incr_oversize_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_read_no_incr_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_series_write_read_incr_with_error_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_read_random_ops_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_read_security_gating_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_single_write_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_single_read_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_series_no_incr_write_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_series_no_incr_read_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_series_incr_write_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_series_incr_read_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_series_incr_write_with_status_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_series_incr_read_with_status_test.svh"
`include "dtp_jtag2axi_smc_otp_axi_error_security_gating_test.svh"

// SEP OTP JTAG2AXI scenarios.
`include "dtp_jtag2axi_sep_otp_axi_single_write_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_single_write_data_verify_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_series_write_incr_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_series_write_no_incr_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_series_write_incr_with_error_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_random_ops_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_write_security_gating_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_single_write_read_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_series_write_read_incr_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_series_write_read_no_incr_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_series_write_read_incr_with_error_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_read_random_ops_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_read_security_gating_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_single_write_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_single_read_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_series_no_incr_write_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_series_no_incr_read_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_series_incr_write_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_series_incr_read_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_series_incr_write_with_status_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_series_incr_read_with_status_test.svh"
`include "dtp_jtag2axi_sep_otp_axi_error_security_gating_test.svh"

// Cross-bridge JTAG2AXI robustness scenarios (all three bridges).
`include "dtp_jtag2axi_robustness_base_test.svh"
`include "dtp_jtag2axi_backpressure_aw_before_w_test.svh"
`include "dtp_jtag2axi_backpressure_long_stall_test.svh"
`include "dtp_jtag2axi_backpressure_abort_at_data_w_test.svh"
`include "dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test.svh"
`include "dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test.svh"
`include "dtp_jtag2axi_decode_error_decerr_write_test.svh"
`include "dtp_jtag2axi_decode_error_decerr_read_test.svh"
`include "dtp_jtag2axi_decode_error_mixed_test.svh"
`include "dtp_jtag2axi_series_corner_all_bridges_test.svh"

// Debug-TDR scenarios (TMP / IC_RESET / DEBUG_CONTROL / CAPS).
`include "dtp_jtag_tmp_status_register_smoke_test.svh"
`include "dtp_jtag_tmp_status_chrst_n_in_persistence_test.svh"
`include "dtp_jtag_tmp_status_bypass_escape_test.svh"
`include "dtp_jtag_ic_reset_test.svh"
`include "dtp_dbg_jtag_caps_test.svh"
`include "dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test.svh"
`include "dtp_dbg_ctrl_clk_stop_cla_clock_stop_test.svh"
`include "dtp_dbg_ctrl_clk_stop_random_clock_stop_test.svh"
`include "dtp_dbg_ctrl_boot_stall_test.svh"
`include "dtp_dbg_smc_jtag2axi_caps_test.svh"
`include "dtp_dbg_smc_otp_jtag2axi_caps_test.svh"
`include "dtp_dbg_sep_otp_jtag2axi_caps_test.svh"

// Scan-network scenarios (iJTAG SIBs / STAP 3DCR / dbg_disable matrices).
`include "dtp_ijtag_sib_all_off_test.svh"
`include "dtp_ijtag_sib_all_on_test.svh"
`include "dtp_ijtag_sib_random_test.svh"
`include "dtp_ijtag_dft_test.svh"
`include "dtp_ijtag_dfd_test.svh"
`include "dtp_3dcr_stap_sel_ds_test.svh"
`include "dtp_3dcr_stap_sel_smc_test.svh"
`include "dtp_3dcr_stap_sel_sep_test.svh"
`include "dtp_3dcr_stap_sel_extra_test.svh"
`include "dtp_ext_stap_scan_test.svh"
`include "dtp_stap_chain_hold_test.svh"
`include "dtp_3dcr_config_hold_test.svh"
`include "dtp_3dcr_tms_hold_test.svh"
`include "dtp_scan_dbg_disable_matrix_test.svh"
`include "dtp_jtag2axi_dbg_disable_matrix_test.svh"

// Cross-trigger scenarios (XTRIG CSR / CTP protocols / CTM routing).
`include "dtp_xtrig_base_test.svh"
`include "dtp_xtrig_reg_stall_test.svh"
`include "dtp_xtrig_rand_deterministic_csr_sweep_test.svh"
`include "dtp_ctm_rand_deterministic_csr_sweep_test.svh"
`include "dtp_ctm_rand_all_source_select_coverage_test.svh"
`include "dtp_xtrig_axi_channel_skew_test.svh"
`include "dtp_xtrig_axi_channel_skew_demux_aw_lock_release_test.svh"
`include "dtp_xtrig_axi_channel_skew_read_decode_backpressure_test.svh"
`include "dtp_xtrig_axi_outstanding_test.svh"
`include "dtp_xtrig_wire_or_test.svh"
`include "dtp_xtrig_wire_or_bus_test.svh"
`include "dtp_xtrig_p2p_test.svh"
`include "dtp_xtrig_reset_test.svh"
`include "dtp_xtrig_rand_test.svh"
`include "dtp_xtrig_rand_deterministic_dst_port_sweep_test.svh"
`include "dtp_ctm_wire_or_cla_to_ctp_test.svh"
`include "dtp_ctm_wire_or_ctp_to_cla_test.svh"
`include "dtp_ctm_wire_or_cla_to_cla_test.svh"
`include "dtp_ctm_wire_or_ctp_to_ctp_test.svh"
`include "dtp_ctm_p2p_cla_to_ctp_test.svh"
`include "dtp_ctm_p2p_ctp_to_cla_test.svh"
`include "dtp_ctm_p2p_cla_to_cla_test.svh"
`include "dtp_ctm_p2p_ctp_to_ctp_test.svh"
`include "dtp_ctm_reset_wire_or_mode_test.svh"
`include "dtp_ctm_reset_p2p_mode_test.svh"
`include "dtp_ctm_reset_all_modes_test.svh"
`include "dtp_ctm_rand_all_scenarios_test.svh"
`include "dtp_ctm_rand_wire_or_only_test.svh"
`include "dtp_ctm_rand_p2p_only_test.svh"
`include "dtp_ctm_rand_cla_to_ctp_test.svh"
`include "dtp_ctm_rand_ctp_to_cla_test.svh"

// Adopter overlay hook: an external (non-OSS) build may append vendor-
// specific test classes -- e.g. a commercial-VIP overlay -- by defining
// DTP_OVERLAY_TESTS to the quoted name of an include file on its own
// include path. Never defined by the OSS flists.
`ifdef DTP_OVERLAY_TESTS
`include `DTP_OVERLAY_TESTS
`endif
