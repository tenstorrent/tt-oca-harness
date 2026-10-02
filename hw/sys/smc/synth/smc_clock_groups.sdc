# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC asynchronous clock groups.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Sourced after smc_clocks.sdc.
#-----------------------------------------------------------------------------

source [file normalize [file join [file dirname [info script]] \
    ../../../../flows/synth/constraints/async_clock_groups.tcl]]

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# The two AVS families are already `-logically_exclusive` above, so `-exclude`
# keeps them out of the asynchronous declaration -- a clock pair cannot carry
# both relationships. Their async relationship with every other clock is
# unaffected.

# Register the generated clocks SMC defines against their canonical domains, so a parent
# run that replays these constraints merges them into its own grouping. Registrations are
# level-independent; the grouping itself is block-top work.
cdc_group_extra REFCLK {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
cdc_group_extra PERIPHERALCLK {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
cdc_group_extra SPICLK {SPICLK_IN_GPIO SPICLK_OUT_GPIO}

# The memory-interface clocks are -divide_by 1 -combinational copies of SMCCLK and belong
# in its group; without this each raises SETUP_CLOCK_GROUP_MISSING. Collected by glob so
# the scratch-RAM count stays in one place. Block-top only, since the stamps are too.
if {[cdc_is_block_top]} {
    set _smc_mem_gen_clks [list]
    foreach_in_collection c [get_clocks SMCCLK_* -quiet] {
        lappend _smc_mem_gen_clks [get_object_name $c]
    }
    if {[llength $_smc_mem_gen_clks] > 0} {
        cdc_group_extra SMCCLK $_smc_mem_gen_clks
    }
    unset -nocomplain _smc_mem_gen_clks
}

if {[cdc_is_block_top]} {
    cdc_apply_async_groups {
        REFCLK
        SMCCLK
        PERIPHERALCLK
        SPICLK
        TELEMETRYCLK
        JTAG_TCK
        ck_feedthru
    } -exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}
}
