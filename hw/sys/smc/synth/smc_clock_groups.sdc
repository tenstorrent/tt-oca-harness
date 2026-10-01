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

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# The two AVS families are already `-logically_exclusive` above, so `-exclude`
# keeps them out of the asynchronous declaration -- a clock pair cannot carry
# both relationships. Their async relationship with every other clock is
# unaffected.

set_async_clock_groups {
    {REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
    {SMCCLK SMCCLK_*}
    {PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
    {SPICLK SPICLK_IN_GPIO SPICLK_OUT_GPIO}
    {TELEMETRYCLK}
    {JTAG_TCK}
    {ck_feedthru}
} -exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}
