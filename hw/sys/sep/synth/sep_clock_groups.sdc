# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP asynchronous clock groups.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Sourced after sep_clocks.sdc, and after
# sep_entropy_clocks.sdc on a flow that stamps the entropy tree: groups that
# match no clock are dropped, so the one list below serves a flow with the
# entropy tree and a flow without it.
#
# Applied through set_async_clock_groups, so every flow that sources this file
# gets the groups with -allow_paths and the default inter-group bounds. See
# flows/synth/constraints/async_clock_groups.tcl.
#
# The two entropy sample-clock families are -logically_exclusive where they are
# stamped, so -exclude keeps that one pair out of the asynchronous declaration:
# a clock pair cannot carry both relationships.
#-----------------------------------------------------------------------------

source [file normalize [file join [file dirname [info script]] \
    ../../../../flows/synth/constraints/async_clock_groups.tcl]]

set_async_clock_groups {
    {SEPCLK SEPCLK_PKA_IMEM SEPCLK_PKA_DMEM SEPCLK_CPU_TCM}
    {REFCLK}
    {WDTCLK}
    {JTAG_TCK}
    {ENTROPY_ROSC_CLK  ENTROPY_SCLK_FROM_ROSC_*}
    {ENTROPY_SHARED_RO ENTROPY_SCLK_FROM_SHARED_RO_*}
    {ENTROPY_DBG_MON_*}
    {ck_feedthru}
} -exclude {{ENTROPY_*ROSC* ENTROPY_*SHARED_RO*}}
