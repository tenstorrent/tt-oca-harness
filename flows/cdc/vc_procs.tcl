# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# vc_procs.tcl - sign-off helpers on top of the hierarchy-reuse hooks
#
# The procs here wrap VC SpyGlass CDC/RDC commands (create_reset,
# configure_cdc_convergence) so a block's reset and convergence constraints
# can be replayed under a parent's ::cdc_hier_prefix. The generic hooks they
# build on live in flows/synth/constraints/cdc_hier_procs.tcl, which is
# sourced here when missing.
################################################################################

if { [info procs cdc_is_block_top] eq "" } {
    if { [info script] ne "" } {
        source [file normalize [file dirname [info script]]/../synth/constraints/cdc_hier_procs.tcl]
    } elseif { [info exists ::env(GIT_ROOT)] } {
        source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
    } else {
        error "vc_procs.tcl: cannot locate cdc_hier_procs.tcl; set GIT_ROOT"
    }
}

# create_reset for a block TOP-PORT reset.
# - Block top: plain create_reset on the port.
# - Parent, name aliased: SKIPPED - the driver net already carries the parent's reset
#   (::cdc_reset_alias maps the name for assertion sequences via cdc_rst).
# - Parent, name not aliased: created on the child instance pin, keeping the child's name
#   (a reset that is genuinely internal at the parent, e.g. SMC's JTAG_RESET from DTP).
proc cdc_create_port_reset { name port args } {
    if { ![cdc_is_block_top] && [cdc_rst_is_aliased $name] } {
        puts "INFO: cdc_hier: reset '$name' -> '[cdc_rst $name]' under prefix '$::cdc_hier_prefix' - not re-created"
        return
    }
    set obj [cdc_port_or_pin $port]
    if { ![cdc_is_block_top] && [sizeof_collection $obj] == 0 } {
        puts "WARNING: cdc_hier: reset '$name': no pin matches '${::cdc_hier_prefix}${port}' - skipped"
        return
    }
    create_reset -name $name $obj {*}$args
}

# ---------------------------------------------------------------------------------------
# Single-call convergence configuration.
#
# When configure_cdc_convergence is specified twice, the second call's option values
# override the first's (the tool reports SETUP_OVERRIDE_COMMAND). Every constraint file
# therefore routes its ignore-among contributions through cdc_conv_ignore_among, which
# unions all contributions; cdc_conv_apply emits ONE cumulative call after every file
# has contributed.
#
# All contributed signals are independent control/gray/debug signals with no cross-
# coherency requirement (see each contributing site's rationale).
#
#   -allow_multiple_sync data: only DATA synchronizers participate in
#   CDC_COHERENCY_MULTI_SYNC; multi-domain RESET distribution (one stretcher feeding
#   per-domain prim_sync_reset chains) is intentional across this design.
# ---------------------------------------------------------------------------------------

if { ![info exists ::cdc_conv_union] } { set ::cdc_conv_union [list] }
if { ![info exists ::cdc_conv_at] } { set ::cdc_conv_at [list] }

# Normalize a contribution to a flat list of object NAMES. Contributors pass either a
# Tcl list of names (get_object_name output) or a raw collection handle (get_pins /
# add_to_collection result).
proc cdc_conv_names { objs } {
    set out [list]
    foreach s $objs {
        if { [regexp {^_sel\d+$} $s] } {
            foreach n [get_object_name $s] { lappend out $n }
        } else {
            lappend out $s
        }
    }
    return $out
}
proc cdc_conv_ignore_among { signals } {
    foreach s [cdc_conv_names $signals] {
        if { ![info exists ::cdc_conv_seen($s)] } {
            set ::cdc_conv_seen($s) 1
            lappend ::cdc_conv_union $s
        }
    }
}

# Contribute convergence POINTS (nets/pins/ports) at which convergence reporting is
# intentional fan-in and should be suppressed (-ignore_at_objects).
proc cdc_conv_ignore_at { objects } {
    foreach s [cdc_conv_names $objects] {
        if { ![info exists ::cdc_conv_at_seen($s)] } {
            set ::cdc_conv_at_seen($s) 1
            lappend ::cdc_conv_at $s
        }
    }
}

# Emit the ONE cumulative call, after every constraint file has contributed (a second
# emission would raise SETUP_OVERRIDE_COMMAND, hence apply-once).
proc cdc_conv_apply { } {
    set cmd [list configure_cdc_convergence -allow_multiple_sync data]
    if { [llength $::cdc_conv_union] > 1 } { lappend cmd -ignore_among_signals $::cdc_conv_union }
    if { [llength $::cdc_conv_at] > 0 } { lappend cmd -ignore_at_objects $::cdc_conv_at }
    set stray [lsearch -all -inline -regexp [concat $::cdc_conv_union $::cdc_conv_at] {^_sel\d+$}]
    if { [llength $stray] > 0 } {
        puts "WARNING: cdc_hier: [llength $stray] collection handle(s) reached cdc_conv_apply un-expanded: $stray"
    }
    {*}$cmd
    puts "INFO: cdc_hier: applied convergence config (-allow_multiple_sync data, ignore-among [llength $::cdc_conv_union], ignore-at [llength $::cdc_conv_at])"
}

puts "INFO: vc_procs loaded"
