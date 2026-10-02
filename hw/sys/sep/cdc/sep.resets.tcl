# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
##########
# RESETS
##########
# Hierarchy-reusable: anchored paths go through cdc_inst. Port resets go through
# cdc_create_port_reset -- at the SMU top they are skipped, because ::cdc_reset_alias maps
# them onto SMU's reset tree (RST_NI -> PRIMARY_RESET_N_SMC_CLK, DBG_RSTB_I ->
# POWERGOOD_STABLE_N, ...), and assertion-sequence name lists map through cdc_rst/cdc_clk.

if { [info procs cdc_create_port_reset] eq "" } {
    source $::env(GIT_ROOT)/flows/cdc/vc_procs.tcl
}

# Top-level reset pads
cdc_create_port_reset RST_NI "rst_ni" -async -type reset -value low -disable_assertions_db
cdc_create_port_reset WDT_RST_NI "wdt_rst_ni" -async -type reset -value low -disable_assertions_db
cdc_create_port_reset DBG_RSTB_I "dbg_rstb_i" -async -type reset -value low -disable_assertions_db
cdc_create_port_reset JTAG_TRST_N "jtag_trst_ni" -async -type reset -value low -disable_assertions_db

# Efuse-sense-done reset from sep_crypto
create_reset -name SEP_INTERMEDIATE_RESET_N [cdc_inst "u_sep_crypto/sep_intermediate_reset_no"] -both -type reset -value low -disable_assertions_db

# Main functional reset (post efuse-sense, post JTAG override)
create_reset -name SEP_RESET_N [cdc_inst "u_sep_reset_ctrl/sep_reset_no"] -both -type reset -value low -disable_assertions_db

# CPU reset = sep_reset_n & wdt_rst_ni
create_reset -name SEP_CPU_RESET_N [cdc_inst "u_sep_reset_ctrl/sep_cpu_reset_no"] -both -type reset -value low -disable_assertions_db

# WDT-clock reset sync of rst_ni
create_reset -name RST_WDT_N [cdc_inst "u_sep_wdt_wrap/u_rst_wdt_sync/sync_rst_no"] -both -type reset -value low -disable_assertions_db

# Per-accelerator software resets
# Isolation-sequenced outputs from the reset controller
create_reset -name SEP_SW_RST_KM [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.km"] -async -type reset -value low -disable_assertions_db
create_reset -name SEP_SW_RST_OTBN [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.otbn"] -async -type reset -value low -disable_assertions_db
create_reset -name SEP_SW_RST_AES [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.aes"] -async -type reset -value low -disable_assertions_db
create_reset -name SEP_SW_RST_HMAC [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.hmac"] -async -type reset -value low -disable_assertions_db
create_reset -name SEP_SW_RST_KMAC [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.kmac"] -async -type reset -value low -disable_assertions_db
create_reset -name SEP_SW_RST_TRNG [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.trng"] -async -type reset -value low -disable_assertions_db
create_reset -name SEP_SW_RST_ABR [cdc_inst "u_sep_reset_ctrl/sep_crypto_gated_rst_no.abr"] -async -type reset -value low -disable_assertions_db

# Key Manager reset conditioner outputs
create_reset -name KM_COLD_RESET_N [cdc_inst "u_sep_crypto/u_key_manager_s3c_scan/u_reset_conditioner/rst_cold_aasd_no"] -async -type reset -value low -disable_assertions_db
create_reset -name KM_WARM_RESET_N [cdc_inst "u_sep_crypto/u_key_manager_s3c_scan/u_reset_conditioner/rst_warm_sync_no"] -both -type reset -value low -disable_assertions_db

# Reference-counter reset syncs into SEPCLK and REFCLK domains
create_reset -name SEP_RESET_N_REFCNT_SEP_CLK [cdc_inst "u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_prst_wr_clk_domain_sync/gen_rst_sync_stage\[15\].u_sync_dffr/d0nt_dffr/Q"] -both -type reset -value low -disable_assertions_db
create_reset -name SEP_RESET_N_REFCNT_REF_CLK [cdc_inst "u_sep_system_peripherals/u_sep_system_csr/u_reference_counter_counter/u_prst_rd_clk_domain_sync/gen_rst_sync_stage\[15\].u_sync_dffr/d0nt_dffr/Q"] -both -type reset -value low -disable_assertions_db

##############################
# RESET ASSERTION SEQUENCES
##############################

# DBG_RSTB_I is powergood_stable at SMU; primary reset (rst_ni) asserts with it and all clocks are absent
# Port-reset and clock names map through cdc_rst / cdc_clk so these sequences survive at
# the SMU top with the parent's names; SEP-internal reset names are level-independent.
set_rdc_define_assertion_sequence -from_reset [cdc_rst {DBG_RSTB_I}] -to_reset [cdc_rst {RST_NI}]
set_rdc_define_assertion_sequence -from_reset [cdc_rst {DBG_RSTB_I}] -to_clock [cdc_clk {SEPCLK REFCLK WDTCLK JTAG_TCK ck_feedthru ENTROPY_ROSC_CLK}]
set_rdc_define_assertion_sequence -from_reset [cdc_rst {RST_NI}] -to_reset {SEP_INTERMEDIATE_RESET_N}
set_rdc_define_assertion_sequence -from_reset {SEP_INTERMEDIATE_RESET_N} -to_reset {SEP_RESET_N}
set_rdc_define_assertion_sequence -from_reset [cdc_rst {SEP_RESET_N WDT_RST_NI}] -to_reset {SEP_CPU_RESET_N}
set_rdc_define_assertion_sequence -from_reset {SEP_RESET_N} -to_reset {SEP_SW_RST_KM SEP_SW_RST_OTBN SEP_SW_RST_AES SEP_SW_RST_HMAC SEP_SW_RST_KMAC SEP_SW_RST_TRNG SEP_SW_RST_ABR}
set_rdc_define_assertion_sequence -from_reset [cdc_rst {RST_NI}] -to_reset {RST_WDT_N}
set_rdc_define_assertion_sequence -from_reset {SEP_RESET_N} -to_reset {KM_COLD_RESET_N}
set_rdc_define_assertion_sequence -from_reset {KM_COLD_RESET_N} -to_reset {KM_WARM_RESET_N}
set_rdc_define_assertion_sequence -from_reset {SEP_RESET_N} -to_reset {SEP_RESET_N_REFCNT_SEP_CLK SEP_RESET_N_REFCNT_REF_CLK}
