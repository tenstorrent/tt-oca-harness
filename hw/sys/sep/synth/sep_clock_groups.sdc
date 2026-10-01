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

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# The two entropy sample-clock families are already `-logically_exclusive`
# above, so `-exclude` keeps that one pair out of the asynchronous declaration
# -- a clock pair cannot carry both relationships. Groups matching no clock are
# dropped, so the entropy groups cost nothing while `entropy_source` is
# blackboxed.

# Register the generated clocks SEP defines against their canonical domains, so a
# parent run that replays these constraints merges them into its own grouping. The
# registration is level-independent; only the grouping itself is block-top work.
cdc_group_extra SEPCLK            {SEPCLK_PKA_IMEM SEPCLK_PKA_DMEM SEPCLK_CPU_TCM}
cdc_group_extra ENTROPY_ROSC_CLK  {ENTROPY_SCLK_FROM_ROSC_*}
cdc_group_extra ENTROPY_SHARED_RO {ENTROPY_SCLK_FROM_SHARED_RO_*}

if {[cdc_is_block_top]} {
    cdc_apply_async_groups {
        SEPCLK
        REFCLK
        WDTCLK
        JTAG_TCK
        ENTROPY_ROSC_CLK
        ENTROPY_SHARED_RO
        ENTROPY_DBG_MON_*
        ck_feedthru
    } -exclude {{ENTROPY_*ROSC* ENTROPY_*SHARED_RO*}}
}


