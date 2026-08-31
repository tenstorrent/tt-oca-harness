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
`include "dtp_jtag2axi_smc_axi_series_write_no_incr_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_incr_with_error_test.svh"
`include "dtp_jtag2axi_smc_axi_random_ops_test.svh"
`include "dtp_jtag2axi_smc_axi_write_security_gating_test.svh"
`include "dtp_jtag2axi_smc_axi_series_write_read_incr_test.svh"
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

// Adopter overlay hook: an external (non-OSS) build may append vendor-
// specific test classes -- e.g. a commercial-VIP overlay -- by defining
// DTP_OVERLAY_TESTS to the quoted name of an include file on its own
// include path. Never defined by the OSS flists.
`ifdef DTP_OVERLAY_TESTS
`include `DTP_OVERLAY_TESTS
`endif
