# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# smc_cdc_max_delay.tcl - SMC CDC max_delay constraints
#
# The per-instance calls live in smc_cdc_max_delay_generated.tcl, enumerated
# offline from the elaborated design. This file holds only what a human decides:
# overrides, exclusions, and notes.
#
# Sourced from constraints.sdc in this directory, after the clock stampings and
# set_async_clock_groups. See "CDC Timing Constraints" in the Integrator Guide.
################################################################################

################################################################################
# GENERATED-CLOCK PERIODS
################################################################################
# A generated clock carries no readable `period` attribute, so the periods of the
# AVS clocks have to be stated. Derived from their create_generated_clock in
# constraints.sdc, where divide_by N means N x the master's period. Keep these
# in step with that file.
set ::cdc_clock_period(AVS_CLKMUX_OUTPUT_FROM_REFCLK) \
    $clock_periods(REFCLK_PERIOD)
set ::cdc_clock_period(AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK) \
    $clock_periods(PERIPHERALCLK_PERIOD)
set ::cdc_clock_period(AVS_CLK_DIV_CLK_O_FROM_REFCLK) \
    [expr { 2 * $clock_periods(REFCLK_PERIOD) }]
set ::cdc_clock_period(AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK) \
    [expr { 4 * $clock_periods(PERIPHERALCLK_PERIOD) }]
set ::cdc_clock_period(AVS_CLK_FROM_REFCLK) \
    [expr { 2 * $clock_periods(REFCLK_PERIOD) }]
set ::cdc_clock_period(AVS_CLK_FROM_PERIPHERALCLK) \
    [expr { 4 * $clock_periods(PERIPHERALCLK_PERIOD) }]

source [file join $ocah_sdc_dir smc_cdc_max_delay_generated.tcl]

################################################################################
# OVERRIDES
################################################################################
# Every proc takes an optional trailing delay in ps that replaces the computed
# value, for the cases where 0.5 * T_dst or 1.0 * T_dst will not close:
#
#   set_cdc_max_delay_axi_cdc <path> PERIPHERALCLK SMCCLK 2000
#
# Re-stating a call here after the source above wins, since the later exception
# is the one the tool keeps for identical object specifications. Empty is the
# expected steady state; each entry needs a reason.

################################################################################
cdc_max_delay_summary
