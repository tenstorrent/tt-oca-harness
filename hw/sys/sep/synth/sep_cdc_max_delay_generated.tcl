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

# ---- prim_sync2r (1 instances) ----
set_cdc_max_delay_prim_sync2 sep_cpu/u_mpc_reset_run_req_sync SEPCLK

# ---- prim_sync3 (2 instances) ----
set_cdc_max_delay_prim_sync3 sep_system_peripherals/u_sep_system_csr/reference_counter_counter/sync_cnt_en_count REFCLK
set_cdc_max_delay_prim_sync3 sep_system_peripherals/u_sep_system_csr/reference_counter_counter/sync_ref_count SEPCLK

# ---- prim_sync_reset (3 instances) ----
set_cdc_max_delay_prim_sync_reset sep_system_peripherals/u_sep_system_csr/reference_counter_counter/prst_rd_clk_domain_sync REFCLK
set_cdc_max_delay_prim_sync_reset sep_system_peripherals/u_sep_system_csr/reference_counter_counter/prst_wr_clk_domain_sync SEPCLK
set_cdc_max_delay_prim_sync_reset u_sep_wdt_wrap/u_rst_wdt_sync WDTCLK

# ---- prim_fifo_async (1 instances) ----
set_cdc_max_delay_prim_fifo_async sep_system_peripherals/u_sep_system_csr/reference_counter_counter/cnt_update_async_fifo SEPCLK REFCLK

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
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data sep_crypto/aes_wrapper_s3c_scan/tt_aes/u_prim_sync_reqack_data SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data sep_crypto/kmac_wrapper_s3c_scan/tt_kmac/gen_entropy.u_prim_sync_reqack_data SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data sep_crypto/sep_crypto_otbn_wrapper_s3c_scan/u_otbn/u_otbn_scramble_ctrl/u_otp_key_req_sync SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data sep_crypto/sep_crypto_otbn_wrapper_s3c_scan/u_otbn/u_prim_edn_rnd_req/u_prim_sync_reqack_data SEPCLK SEPCLK
# SAME CLOCK, not a crossing: set_cdc_max_delay_prim_sync_reqack_data sep_crypto/sep_crypto_otbn_wrapper_s3c_scan/u_otbn/u_prim_edn_urnd_req/u_prim_sync_reqack_data SEPCLK SEPCLK

# ---- dmi_wrapper (1 instances) ----
set_cdc_max_delay_dmi_wrapper sep_cpu/el2_veer_wrapper/dmi_wrapper SEPCLK
