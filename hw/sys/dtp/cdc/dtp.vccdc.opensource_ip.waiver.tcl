# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP VC SpyGlass CDC waivers for third-party IP (PULP common_cells and axi).

# For waiving CDC violations on open-source 3rd party IP

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
# ----------------------------------------------------------------------------------

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# CDC_UNSYNC_DATA           : Partially matched data synchronization scheme on a CDC path
# CDC_COHERENCY_RECONV_COMB : Combinational convergence of synchronized signals from the same source domain
# CDC_COHERENCY_RECONV_SEQ  : Sequential convergence of synchronized signals from the same source domain
#=======================================================================================================================
