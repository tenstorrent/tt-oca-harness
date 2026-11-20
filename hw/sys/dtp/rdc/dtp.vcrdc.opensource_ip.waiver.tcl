# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP VC SpyGlass RDC waivers for third-party IP (PULP common_cells and axi).

# For waiving RDC violations on open-source 3rd party IP

# --- hierarchy-reuse tokens -------------------------------------------------------
# ${PREFIX} re-anchors hierarchical filter fields at the parent instance path. A parent
# run that replays this block predefines PREFIX and apply_prefix before sourcing this
# file; in the block's own run PREFIX is "". ${BLOCKINST} is the containing instance of a
# block-top violation (the design name here, the instance path at the parent).
if { ![info exists PREFIX] } { set PREFIX "" }
if { [info procs apply_prefix] eq "" } {
    proc apply_prefix { filter } {
        set out [string map [list {${PREFIX}} $::PREFIX] $filter]
        if { $::PREFIX eq "" } {
            set bi $::env(DESIGN_NAME)
        } else {
            set bi [string trimright $::PREFIX "/."]
        }
        set out [string map [list {${BLOCKINST}} $bi] $out]
        return $out
    }
}
# ${MODPREFIX} is the module-name prefix of a design whose modules are renamed
# <prefix>_<name> ("" otherwise); apply_modprefix substitutes it in Module filters and
# is independent of apply_prefix, which a parent run may replace.
if { ![info exists ::MODPREFIX] } { set ::MODPREFIX "" }
if { [info procs apply_modprefix] eq "" } {
    proc apply_modprefix { filter } {
        return [string map [list {${MODPREFIX}} $::MODPREFIX] $filter]
    }
}
# ----------------------------------------------------------------------------------

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# RDC_CORRUPT_OBSERVED : Asynchronous reset assertion at one flop observed at a destination flop with no
#                       matching reset (the tool cannot prove a blocking scheme protects the destination).
#=======================================================================================================================
