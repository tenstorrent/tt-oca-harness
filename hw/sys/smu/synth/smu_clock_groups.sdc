# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMU clock groups.
#
# Shared with the closed block flow. Source smu_clocks.sdc first: the groups
# name clocks it stamps.
#-----------------------------------------------------------------------------

if {![info exists smu_owns_child_copies]} {
    error "smu_clock_groups.sdc: source smu_clocks.sdc before this file"
}

# under a SAM flow they are not defined here, and under a flat replay the child
# that defines them registers them itself.
set smu_refclk_async_grp {REFCLK}
set smu_periph_async_grp {PERIPHERALCLK}
if {$smu_owns_child_copies} {
    set smu_refclk_async_grp {REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
    set smu_periph_async_grp {PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
}

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# Under the SAM flow the AVS groups collapse to the bare parents and the
# `-exclude` matches nothing, which is harmless. With full hierarchy the two AVS
# families are already `-logically_exclusive` above, so `-exclude` keeps them out
# of the asynchronous declaration -- a clock pair cannot carry both
# relationships. Their async relationship with every other clock is unaffected.
source [file normalize [file join [file dirname [info script]] \
    ../../../../flows/synth/constraints/async_clock_groups.tcl]]

# Register SMU's own generated clocks against their domains. A flat run that
# replays the children applies one merged grouping after the last of them and
# builds each group from these registrations, so it must not be declared per
# block here; the block-top declaration below names the same clocks by glob.
set smu_mem_gen_clks [list]
foreach_in_collection c [get_clocks SMUCLK_* -quiet] {
    lappend smu_mem_gen_clks [get_object_name $c]
}
if {[llength $smu_mem_gen_clks] > 0} {
    cdc_group_extra SMUCLK $smu_mem_gen_clks
}
unset -nocomplain smu_mem_gen_clks
set smu_tck_gen_clks {JTAG_STAP_IO_TCK JTAG_STAP_EXTRA_TCK JTAG_BSR_TCK JTAG_STAP_SCAN_TCK JTAG_DFD_TCK JTAG_DFT_SECURE_TCK JTAG_DFT_TCK}
foreach_in_collection c [get_clocks JTAG_TCK_* -quiet] {
    lappend smu_tck_gen_clks [get_object_name $c]
}
cdc_group_extra JTAG_TCK $smu_tck_gen_clks
unset -nocomplain smu_tck_gen_clks

if {!$smu_inherit_children} {
    set_async_clock_groups [list \
        $smu_refclk_async_grp \
        {SMUCLK SMUCLK_*} \
        $smu_periph_async_grp \
        {TELEMETRYCLK} \
        {JTAG_TCK JTAG_STAP_IO_TCK JTAG_STAP_EXTRA_TCK JTAG_BSR_TCK JTAG_STAP_SCAN_TCK JTAG_DFD_TCK JTAG_DFT_SECURE_TCK JTAG_DFT_TCK JTAG_TCK_*} \
        {SEP_WDT_CLK} \
        {ck_feedthru} \
    ] -exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}
}
