# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# sep_cdc_max_delay_generated.tcl - GENERATED, do not hand-edit
#
# One call per CDC element in the SEP design, enumerated offline against the
# elaborated netlist. The procs it calls come from
# flows/synth/constraints/cdc_max_delay_procs.tcl; constraints.sdc sources both.
#
# Paths and clock names are OCAH's. To apply this file to a design that
# instantiates the block elsewhere, or drives it from differently named clocks,
# set ::cdc_hier_prefix / ::cdc_clock_alias rather than editing here.
#
# Regeneration runs in the closed synthesis flow, not here, and is needed only
# when the block is reconfigured such that the set of CDC elements changes. The
# file goes stale silently in that case - nothing warns about an element that
# was never listed. Hand-written overrides belong in sep_cdc_max_delay.tcl,
# which sources this file.
################################################################################

# Hierarchical instance paths below run past 100 characters and cannot be wrapped:
# a Tcl word does not survive a line break. Brace-quoted words keep a trailing
# backslash-newline literal, and inside quotes it collapses to a space, either way
# corrupting the path. Only the length rule is disabled; the rest still apply.
# tclint-disable line-length

# ---- prim_sync2r (3 instances) ----
set_cdc_max_delay_prim_sync2 u_sep_cpu/u_mpc_reset_run_req_sync SEPCLK
set_cdc_max_delay_prim_sync2 u_sep_reset_ctrl/u_jtag_ip_ovrd_sync SEPCLK
set_cdc_max_delay_prim_sync2 u_sep_reset_ctrl/u_jtag_ip_val_sync SEPCLK

# ---- prim_sync3 (2 instances) ----
set_cdc_max_delay_prim_sync3 u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_sync_cnt_en_count REFCLK
set_cdc_max_delay_prim_sync3 u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_sync_ref_count SEPCLK

# ---- prim_sync_reset (3 instances) ----
set_cdc_max_delay_prim_sync_reset u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_prst_rd_clk_domain_sync REFCLK
set_cdc_max_delay_prim_sync_reset u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_prst_wr_clk_domain_sync SEPCLK
set_cdc_max_delay_prim_sync_reset u_sep_wdt_wrap/u_rst_wdt_sync WDTCLK

# ---- prim_fifo_async (1 instances) ----
set_cdc_max_delay_prim_fifo_async u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_cnt_update_async_fifo SEPCLK REFCLK

# ---- prim_reg_cdc (10 instances) ----
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wdog_bark_thold_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wdog_bite_thold_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wdog_count_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wdog_ctrl_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wkup_cause_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wkup_count_hi_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wkup_count_lo_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wkup_ctrl_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wkup_thold_hi_cdc SEPCLK WDTCLK
set_cdc_max_delay_prim_reg_cdc u_sep_wdt_wrap/u_wdt_aon_timer/u_reg/u_wkup_thold_lo_cdc SEPCLK WDTCLK

# ---- prim_sync_reqack_data (5 instances) ----
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data u_sep_crypto/u_aes_wrapper_s3c_scan/u_tt_aes/u_prim_sync_reqack_data SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data u_sep_crypto/u_kmac_wrapper_s3c_scan/u_tt_kmac/gen_entropy.u_prim_sync_reqack_data SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data u_sep_crypto/u_sep_crypto_otbn_wrapper_s3c_scan/u_otbn/u_otbn_scramble_ctrl/u_otp_key_req_sync SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data u_sep_crypto/u_sep_crypto_otbn_wrapper_s3c_scan/u_otbn/u_prim_edn_rnd_req/u_prim_sync_reqack_data SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data u_sep_crypto/u_sep_crypto_otbn_wrapper_s3c_scan/u_otbn/u_prim_edn_urnd_req/u_prim_sync_reqack_data SEPCLK SEPCLK

# ---- dmi_wrapper (1 instances) ----
set_cdc_max_delay_dmi_wrapper u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper SEPCLK
