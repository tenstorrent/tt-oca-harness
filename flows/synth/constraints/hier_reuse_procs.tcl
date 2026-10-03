# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# ==================================================================================================
# ===================
# hier_reuse_procs.tcl - adopter hooks for replaying block constraints at a parent level
# ==================================================================================================
# ===================
# Generalizes the ADOPTER HOOKS pattern of flows/synth/constraints/cdc_max_delay_procs.tcl
# (::cdc_hier_prefix / ::cdc_clock_alias, applied by cdc_inst / cdc_clk) to the whole
# constraint set, so a child block's timing and CDC/RDC constraint files
# (hw/sys/<block>/synth/*.sdc and hw/sys/<block>/cdc/*.tcl) can be sourced unchanged by a
# parent run (hw/sys/smu/cdc/smu.cdc_rdc.tcl) with the child re-anchored at its instance path.
#
# The SAME variable names as cdc_max_delay_procs.tcl are shared: one
#   set ::cdc_hier_prefix u_smc/
# drives both the max-delay replay (closed synth flow) and the constraint replay here.
#
# Defaults are identities: with ::cdc_hier_prefix == "" and empty alias arrays, every proc
# below is a no-op wrapper, so a block's OWN run sees its constraints unchanged. Parent runs
# opt in per child via cdc_begin_block/cdc_end_block.
#
# Files that use these procs must tolerate being sourced by a flow that did not load this
# file first (the open synth flow). Give each such file the defensive stanza:
#
#   if {[info procs cdc_is_block_top] eq ""} {
#       source [file join $ocah_flow_constraints_dir hier_reuse_procs.tcl]
#   }
# ==================================================================================================
# ===================

# cdc_inst / cdc_clk and the ::cdc_hier_prefix / ::cdc_clock_alias they read are defined by
# cdc_max_delay_procs.tcl; the async-group registration lives in async_clock_groups.tcl, which
# applies it with -allow_paths and the default bounds. Source whichever is missing.
if { [info procs cdc_inst] eq "" } {
    source [file join [file dirname [file normalize [info script]]] cdc_max_delay_procs.tcl]
}
if { [info procs cdc_group_extra] eq "" } {
    source [file join [file dirname [file normalize [info script]]] async_clock_groups.tcl]
}

if { ![info exists ::cdc_hier_prefix] } { set ::cdc_hier_prefix "" }
if { ![array exists ::cdc_clock_alias] } { array set ::cdc_clock_alias {} }
if { ![array exists ::cdc_reset_alias] } { array set ::cdc_reset_alias {} }
# Scenario the constraints are read for. "synth" (the default, nothing sets it) applies
# every IO delay; "functional" is the VC CDC/RDC run whose case-analysis files pin the
# DFT and strap ports, so those ports get no IO delay there.
if { ![info exists ::cdc_scenario] } { set ::cdc_scenario synth }

# True when constraints are being applied at the block's own top (no re-anchoring).
proc cdc_is_block_top { } { return [expr { $::cdc_hier_prefix eq "" }] }

# True when the case-analysis files pin the DFT/strap ports (VC functional scenario).
proc cdc_ports_pinned { } { return [expr { $::cdc_scenario eq "functional" }] }

# IO delay for a port the functional scenario pins by case analysis: applied in every
# other scenario (synthesis, a DFT-mode VC run), skipped where the port is pinned.
proc cdc_pinned_port_delay { args } {
    if { [cdc_ports_pinned] } { return }
    {*}$args
}

# Prefix a block-relative hierarchical path. Identity at block top.
# Map block-local clock names onto the adopter's. Takes and returns a list, since a muxed
# domain resolves to several clocks.
# Map block-local reset names onto the adopter's (same shape as cdc_clk).
proc cdc_rst { rsts } {
    set out {}
    foreach r $rsts {
        if { [info exists ::cdc_reset_alias($r)] } {
            lappend out $::cdc_reset_alias($r)
        } else {
            lappend out $r
        }
    }
    return $out
}

proc cdc_rst_is_aliased { r } { return [info exists ::cdc_reset_alias($r)] }

# A block-top port reference: get_ports at the block's own top, the instance pin under the
# adopter's prefix otherwise. -quiet at the parent because struct-typed ports can flatten
# to differently shaped pin names; callers that require a match must check sizeof.
proc cdc_port_or_pin { pattern } {
    if { [cdc_is_block_top] } { return [get_ports $pattern] }
    return [get_pins -quiet "${::cdc_hier_prefix}${pattern}"]
}

# create_reset for a block TOP-PORT reset.
# - Block top: plain create_reset on the port (unchanged behaviour).
# - Parent, name aliased: SKIPPED - the driver net already carries the parent's reset
#   (::cdc_reset_alias maps the name for assertion sequences via cdc_rst).
# - Parent, name not aliased: created on the child instance pin, keeping the child's name
#   (a reset that is genuinely internal at the parent, e.g. SMC's JTAG_RESET from DTP).
proc cdc_create_port_reset { name port args } {
    if { ![cdc_is_block_top] && [cdc_rst_is_aliased $name] } {
        puts "INFO: hier_reuse: reset '$name' -> '[cdc_rst $name]' under prefix\
              '$::cdc_hier_prefix' - not re-created"
        return
    }
    set obj [cdc_port_or_pin $port]
    if { ![cdc_is_block_top] && [sizeof_collection $obj] == 0 } {
        puts "WARNING: hier_reuse: reset '$name': no pin matches '${::cdc_hier_prefix}${port}'\
              - skipped"
        return
    }
    create_reset -name $name $obj {*}$args
}

# Register extra clocks (generated clocks a block defines) into a canonical async domain.
# Both the domain name and the clock names go through the alias map, so children register
# with their local names and the parent's table lands them in the right group.
# Emit ONE set_clock_groups -asynchronous over the given canonical domain names.
# Each group = the domain clock itself plus everything registered via cdc_group_extra,
# filtered down to clocks that actually exist in this session. Groups with no existing
# clocks are dropped with an INFO (pattern borrowed from
# flows/synth/constraints/async_clock_groups.tcl) - this is what lets one domain list
# serve full-hier, SMU_SEP=0, and per-block configurations.
# ---------------------------------------------------------------------------------------
# Per-child scoping for a parent aggregator (see hw/sys/smu/cdc/smu.cdc_rdc.tcl):
#
#   cdc_begin_block u_smc/ {SMCCLK SMUCLK} {JTAG_RESET {}}
#   source .../hw/sys/smc/cdc/smc.cdc_rdc.tcl
#   ...
#   cdc_end_block
#
# clock_alias / reset_alias are flat {from to from to ...} lists. Nesting is not
# supported (one level of begin/end at a time).
# ---------------------------------------------------------------------------------------
proc cdc_begin_block { prefix { clock_alias {} } { reset_alias {} } } {
    if { $::cdc_hier_prefix ne "" } {
        puts "WARNING: hier_reuse: cdc_begin_block '$prefix' while prefix '$::cdc_hier_prefix'\
              active - nesting unsupported"
    }
    set ::cdc_hier_prefix $prefix
    array unset ::cdc_clock_alias
    array set ::cdc_clock_alias $clock_alias
    array unset ::cdc_reset_alias
    array set ::cdc_reset_alias $reset_alias
    puts "INFO: hier_reuse: begin block prefix='$prefix' clock_alias={$clock_alias}\
          reset_alias={$reset_alias}"
}

proc cdc_end_block { } {
    puts "INFO: hier_reuse: end block prefix='$::cdc_hier_prefix'"
    set ::cdc_hier_prefix ""
    array unset ::cdc_clock_alias
    array set ::cdc_clock_alias {}
    array unset ::cdc_reset_alias
    array set ::cdc_reset_alias {}
}

# ---------------------------------------------------------------------------------------
# Single-call convergence configuration.

# Per Spyglass documentation:
# "When the configure_cdc_convergence command is specified two times, then the values of
# the options of the second command override the values of the first. VC SpyGlass CDC
# reports this tag to indicate that the values of the options specified with the first
# command are overridden.""
#
# Every constraint file must therefore route its ignore-among contributions through
# cdc_conv_ignore_among, which unions all contributions and re-emits ONE cumulative
# configure_cdc_convergence each time.
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

# Emit the ONE cumulative call. Invoked from each flow's read_sdc_post.tcl hook, after
# every constraint file has contributed (a second emission would raise
# SETUP_OVERRIDE_COMMAND, hence apply-once).
proc cdc_conv_apply { } {
    set cmd [list configure_cdc_convergence -allow_multiple_sync data]
    if { [llength $::cdc_conv_union] > 1 } { lappend cmd -ignore_among_signals $::cdc_conv_union }
    if { [llength $::cdc_conv_at] > 0 } { lappend cmd -ignore_at_objects $::cdc_conv_at }
    set stray [lsearch -all -inline -regexp [concat $::cdc_conv_union $::cdc_conv_at] {^_sel\d+$}]
    if { [llength $stray] > 0 } {
        puts "WARNING: hier_reuse: [llength $stray] collection handle(s) reached cdc_conv_apply\
              un-expanded: $stray"
    }
    {*}$cmd
    puts "INFO: hier_reuse: applied convergence config (-allow_multiple_sync data, ignore-among\
          [llength $::cdc_conv_union], ignore-at [llength $::cdc_conv_at])"
}

puts "INFO: hier_reuse_procs loaded (prefix='$::cdc_hier_prefix')"
