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
#-----------------------------------------------------------------------------

source [file normalize [file join [file dirname [info script]] \
    ../../../../flows/synth/constraints/async_clock_groups.tcl]]

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# The two entropy sample-clock families are already `-logically_exclusive`
# above, so `-exclude` keeps that one pair out of the asynchronous declaration
# -- a clock pair cannot carry both relationships. Groups matching no clock are
# dropped, so the entropy groups cost nothing while `entropy_source` is
# blackboxed.

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


