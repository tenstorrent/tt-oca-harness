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

source -echo [file join $ocah_dtp_flows_dir cdc vc_procs.tcl]

# Clocks, generated clocks, IO delays, async groups (block-top gated inside).
source -echo [file join $ocah_dtp_cdc_dir ../synth/constraints.sdc]

# Shared type-level synchronizer / verified-IP setup (applies once per session).
source -echo [file join $ocah_dtp_flows_dir cdc cdc_rdc_setup.tcl]

source -echo [file join $ocah_dtp_cdc_dir dtp.resets.tcl]
if { $::cdc_app eq "cdc" } {
    source -echo [file join $ocah_dtp_cdc_dir dtp.static_signals.tcl]
}
