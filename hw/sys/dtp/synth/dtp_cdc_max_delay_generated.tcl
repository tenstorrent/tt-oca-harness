# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# dtp_cdc_max_delay_generated.tcl - GENERATED, do not hand-edit
#
# One call per CDC element in the DTP design, enumerated offline against the
# elaborated netlist. The procs it calls come from
# flows/synth/constraints/cdc_max_delay_procs.tcl; constraints.sdc sources both.
#
# Paths and clock names are OCAH's. To apply this file to a design that
# instantiates the block elsewhere, or drives it from differently named clocks,
# set ::cdc_hier_prefix / ::cdc_clock_alias rather than editing here.
#
# Regeneration runs in the closed synthesis flow, not here, and is needed only
# when the block is reconfigured such that the set of CDC elements changes. The
# file goes stale silently in that case - nothing warns about an element that
# was never listed. Hand-written overrides belong in dtp_cdc_max_delay.tcl,
# which sources this file.
################################################################################

# Hierarchical instance paths below run past 100 characters and cannot be wrapped:
# a Tcl word does not survive a line break. Brace-quoted words keep a trailing
# backslash-newline literal, and inside quotes it collapses to a space, either way
# corrupting the path. Only the length rule is disabled; the rest still apply.
# tclint-disable line-length
