# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# dtp.cdc_rdc.tcl -- entry point for the DTP CDC/RDC sign-off constraints
#
# Sources the block's constraint files in dependency order. ::cdc_app selects
# the application: "cdc" (default) also reads the CDC-only quasi-static signals,
# "rdc" leaves them out. A parent that replays this block under a hierarchy
# prefix (hw/sys/smu/cdc/smu.cdc_rdc.tcl) sources this same file; the boundary
# constraints inside are block-top gated.

if { ![info exists ::cdc_app] } { set ::cdc_app cdc }

if { [info script] ne "" } {
    set ocah_dtp_cdc_dir [file dirname [file normalize [info script]]]
} elseif { [info exists ::env(GIT_ROOT)] } {
    set ocah_dtp_cdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/dtp/cdc]
} else {
    error "dtp.cdc_rdc.tcl: cannot locate this file's directory; set GIT_ROOT"
}
set ocah_dtp_flows_dir [file normalize $ocah_dtp_cdc_dir/../../../../flows]

source -echo [file join $ocah_dtp_flows_dir synth constraints hier_reuse_procs.tcl]

# Clocks, generated clocks, async groups and IO delays (block-top gated inside):
# the files the synthesis SDC composes, without its CDC max-delay layer.
source -echo [file join $ocah_dtp_flows_dir synth constraints clock_periods.tcl]
source -echo [file join $ocah_dtp_cdc_dir ../synth/dtp_clocks.sdc]
source -echo [file join $ocah_dtp_cdc_dir ../synth/dtp_clock_groups.sdc]
source -echo [file join $ocah_dtp_cdc_dir ../synth/dtp_io_delays.sdc]

# Shared type-level synchronizer / verified-IP setup (applies once per session).
source -echo [file join $ocah_dtp_flows_dir cdc cdc_rdc_setup.tcl]

source -echo [file join $ocah_dtp_cdc_dir dtp.resets.tcl]
if { $::cdc_app eq "cdc" } {
    source -echo [file join $ocah_dtp_cdc_dir dtp.static_signals.tcl]
}
