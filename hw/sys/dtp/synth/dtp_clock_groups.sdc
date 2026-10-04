# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# DTP asynchronous clock groups.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Sourced after dtp_clocks.sdc: the JTAG_TCK_* glob
# resolves when the call runs, so a generated clock created later would be left
# out of the group and timed against DTPCLK as an unrelated domain.
#-----------------------------------------------------------------------------

source [file normalize [file join [file dirname [info script]] \
    ../../../../flows/synth/constraints/async_clock_groups.tcl]]

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

########################################################
# Declared with `-allow_paths` plus a loose default bound on every inter-group
# clock pair. The per-instance bounds sourced at the end of this file refine
# that default; without `-allow_paths` they would be masked.
#
# This has to come after the TCK passthroughs above: the `JTAG_TCK_*` glob is
# resolved when the call runs, so a generated clock created later would be left
# out of the group and end up timed against DTPCLK as an unrelated domain.

# Register the TCK passthroughs against JTAG_TCK so a parent run that replays these
# constraints merges them into its own grouping. The glob is deliberate: it matches
# whatever dtp_clocks.sdc stamped, so a passthrough cannot be left out of the group by
# a mistyped name -- which is what an explicit list allows, since a name matching no
# clock is dropped silently.
cdc_group_extra JTAG_TCK {JTAG_TCK_*}

if {[cdc_is_block_top]} {
    cdc_apply_async_groups {
        DTPCLK
        JTAG_TCK
        ck_feedthru
    }
}

