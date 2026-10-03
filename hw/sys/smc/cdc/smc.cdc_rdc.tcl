# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# smc.cdc_rdc.tcl -- entry point for the SMC CDC/RDC sign-off constraints
#
# Sources the block's constraint files in dependency order. ::cdc_app selects
# the application: "cdc" (default) also reads the CDC-only quasi-static signals
# and the instance-level convergence constraints, "rdc" leaves them out. A
# parent that replays this block under a hierarchy prefix
# (hw/sys/smu/cdc/smu.cdc_rdc.tcl) sources this same file; the boundary
# constraints inside are block-top gated.

if { ![info exists ::cdc_app] } { set ::cdc_app cdc }

if { [info script] ne "" } {
    set ocah_smc_cdc_dir [file dirname [file normalize [info script]]]
} elseif { [info exists ::env(GIT_ROOT)] } {
    set ocah_smc_cdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smc/cdc]
} else {
    error "smc.cdc_rdc.tcl: cannot locate this file's directory; set GIT_ROOT"
}
set ocah_smc_flows_dir [file normalize $ocah_smc_cdc_dir/../../../../flows]

source -echo [file join $ocah_smc_flows_dir synth constraints hier_reuse_procs.tcl]

# Clocks, generated clocks, async groups and IO delays (block-top gated inside):
# the files the synthesis SDC composes, without its CDC max-delay layer.
source -echo [file join $ocah_smc_flows_dir synth constraints clock_periods.tcl]
source -echo [file join $ocah_smc_cdc_dir ../synth/smc_clocks.sdc]
source -echo [file join $ocah_smc_cdc_dir ../synth/smc_clock_groups.sdc]
source -echo [file join $ocah_smc_cdc_dir ../synth/smc_io_delays.sdc]
source -echo [file join $ocah_smc_cdc_dir ../synth/smc_gpio_io_delays.sdc]

source -echo [file join $ocah_smc_cdc_dir smc.resets.tcl]
source -echo [file join $ocah_smc_cdc_dir smc.case_analysis.tcl]
if { $::cdc_app eq "cdc" } {
    source -echo [file join $ocah_smc_cdc_dir smc.static_signals.tcl]
}

# Shared type-level synchronizer / verified-IP setup (applies once per session),
# then the SMC instance-level annotation.
source -echo [file join $ocah_smc_flows_dir cdc cdc_rdc_setup.tcl]
source -echo [file join $ocah_smc_cdc_dir smc.cdc_rdc_setup.tcl]

# CDC-only: convergence constraints (contributions are emitted once by
# cdc_conv_apply after every file has been read).
if { $::cdc_app eq "cdc" } {
    source -echo [file join $ocah_smc_cdc_dir smc.dfd_debug_bus_mux.tcl]
    source -echo [file join $ocah_smc_cdc_dir smc.cdc_constraints.tcl]
}
