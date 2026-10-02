# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# smu.cdc_rdc.tcl -- entry point for the SMU CDC/RDC sign-off constraints
#
# FLAT run with inherited subcomponent constraints: SMC, DTP and SEP are fully
# elaborated and each block's own entry is re-sourced here, re-anchored at the
# instance path via the hooks in flows/synth/constraints/hier_reuse_procs.tcl
# (cdc_begin_block sets ::cdc_hier_prefix plus the clock/reset name alias
# maps; cdc_end_block restores them). Block boundary constraints (create_clock
# on ports, IO delays, port resets, clock groups) are block-top gated inside
# the child files, so only their INTERNAL constraints replay here.
#
# ::cdc_app selects the application: "cdc" (default) also reads the CDC-only
# quasi-static signals, "rdc" leaves them out; the child entries apply the same
# switch to their own CDC-only files.

if { ![info exists ::cdc_app] } { set ::cdc_app cdc }

if { [info script] ne "" } {
    set ocah_smu_cdc_dir [file dirname [file normalize [info script]]]
} elseif { [info exists ::env(GIT_ROOT)] } {
    set ocah_smu_cdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smu/cdc]
} else {
    error "smu.cdc_rdc.tcl: cannot locate this file's directory; set GIT_ROOT"
}
set ocah_smu_sys_dir [file normalize $ocah_smu_cdc_dir/../..]
set ocah_smu_flows_dir [file normalize $ocah_smu_sys_dir/../../flows]

source -echo [file join $ocah_smu_flows_dir synth constraints hier_reuse_procs.tcl]

# ---------------------------------------------------------------------------------
# SMU boundary truth (prefix "")
# ---------------------------------------------------------------------------------
set smu_inherit_children 1
source -echo [file join $ocah_smu_flows_dir synth constraints clock_periods.tcl]
source -echo [file join $ocah_smu_cdc_dir ../synth/smu_clocks.sdc]
source -echo [file join $ocah_smu_cdc_dir ../synth/smu_clock_groups.sdc]
source -echo [file join $ocah_smu_cdc_dir ../synth/smu_io_delays.sdc]
source -echo [file join $ocah_smu_cdc_dir smu.resets.tcl]
source -echo [file join $ocah_smu_cdc_dir smu.case_analysis.tcl]
if { $::cdc_app eq "cdc" } {
    source -echo [file join $ocah_smu_cdc_dir smu.static_signals.tcl]
}
source -echo [file join $ocah_smu_flows_dir cdc cdc_rdc_setup.tcl]

# ---------------------------------------------------------------------------------
# Inherit SMC (instance u_smc; SMC's SMCCLK is SMU's SMUCLK). The SMC port resets are
# identity-aliased: the SMU top ports are 1:1 feedthroughs and smu.resets.tcl already
# created the same-named resets, so smc.resets.tcl skips re-creating them. JTAG_RESET is
# intentionally NOT aliased -- it is internal at SMU (driven by DTP) and gets created on
# the u_smc/smc_cpu_jtag_reset_i pin.
# ---------------------------------------------------------------------------------
cdc_begin_block u_smc/ \
    {SMCCLK SMUCLK} \
    {POWERGOOD_RESET_N POWERGOOD_RESET_N COLD_RESET_PAD_N COLD_RESET_PAD_N \
     COOL_RESET_FROM_PIN_N COOL_RESET_FROM_PIN_N TELEMETRY_RESET_N TELEMETRY_RESET_N \
     SCAN_RESET_N SCAN_RESET_N}
source -echo [file join $ocah_smu_sys_dir smc cdc smc.cdc_rdc.tcl]
cdc_end_block

# ---------------------------------------------------------------------------------
# Inherit DTP (instance u_dtp; DTP's DTPCLK is SMU's SMUCLK). Its port resets map onto
# the nets that drive them: rst_n_i <- rst_primary_smc_clk_no (SMC PRIMARY_RESET_N_SMC_CLK)
# and pwr_on_rst_ni <- powergood_stable (SMC POWERGOOD_STABLE_N).
# ---------------------------------------------------------------------------------
cdc_begin_block u_dtp/ \
    {DTPCLK SMUCLK} \
    {rst_n_i PRIMARY_RESET_N_SMC_CLK pwr_on_rst_ni POWERGOOD_STABLE_N}
source -echo [file join $ocah_smu_sys_dir dtp cdc dtp.cdc_rdc.tcl]
cdc_end_block

# ---------------------------------------------------------------------------------
# Inherit SEP (instance gen_sep.u_sep -- present only when the SEP parameter is set;
# SMU_SEP=0 elaborates the gen_no_sep stub instead, so the whole section is guarded).
# SEPCLK is SMU's SMUCLK, WDTCLK is SMU's SEP_WDT_CLK. Port resets map onto their
# drivers: RST_NI <- rst_primary_smc_clk_no, DBG_RSTB_I <- powergood_stable,
# WDT_RST_NI <- rst_wdt_n (SMC WDT_RESET_N_SMC_CLK), JTAG_TRST_N <- DTP SEP-STAP trst
# (trst_n_combined; verify against the first flat report -- may need stap_sep_dbg_rst).
# ---------------------------------------------------------------------------------
if { [sizeof_collection [get_cells -quiet gen_sep.u_sep]] > 0 } {
    cdc_begin_block gen_sep.u_sep/ \
        {SEPCLK SMUCLK WDTCLK SEP_WDT_CLK} \
        {RST_NI PRIMARY_RESET_N_SMC_CLK DBG_RSTB_I POWERGOOD_STABLE_N \
         WDT_RST_NI WDT_RESET_N_SMC_CLK JTAG_TRST_N trst_n_combined}
    source -echo [file join $ocah_smu_sys_dir sep cdc sep.cdc_rdc.tcl]
    cdc_end_block
} else {
    puts "INFO: SMU [string toupper $::cdc_app]: gen_sep.u_sep not present (SMU_SEP=0) - SEP constraints skipped"
}

# ---------------------------------------------------------------------------------
# One merged asynchronous clock grouping: each domain's group is its clock plus every
# generated clock registered by the files above (cdc_group_extra); domains whose clocks
# do not exist in this configuration are dropped with an INFO.
# ---------------------------------------------------------------------------------
cdc_apply_async_groups {REFCLK SMUCLK PERIPHERALCLK SPICLK TELEMETRYCLK JTAG_TCK SEP_WDT_CLK ENTROPY_ROSC_CLK ck_feedthru} \
    -exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}
