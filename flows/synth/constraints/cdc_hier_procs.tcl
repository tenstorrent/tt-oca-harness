# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# cdc_hier_procs.tcl - adopter hooks for replaying block constraints at a parent
#
# A block's constraint files (hw/sys/<block>/synth/constraints.sdc and the
# CDC/RDC sign-off files under hw/sys/<block>/cdc/) are written against the
# block's own top. The procs here let a parent design source those same files
# unchanged with the block re-anchored at its instance path: hw/sys/smu does
# this for smc, dtp and sep.
#
# Hooks (all default to identities, so a block's own run is unchanged):
#   ::cdc_hier_prefix        instance path prefix, e.g. u_smc/
#   ::cdc_clock_alias(<clk>) block clock name -> parent clock name
#   ::cdc_reset_alias(<rst>) block reset name -> parent reset name
#   ::cdc_scenario           synth (default) | functional
#   ::cdc_bound_crossings    1 (default) bounds the crossings in the synth
#                            scenario: async groups with -allow_paths plus the
#                            default bounds, and the block's per-instance
#                            max-delay layer; 0 declares bare async groups and
#                            applies no bound
#
# The "functional" scenario is the CDC/RDC sign-off run: its case-analysis
# files pin the DFT and strap ports, so cdc_pinned_port_delay skips the IO
# delays on those ports, and the async groups are always the bare form. "synth"
# applies every IO delay and, with ::cdc_bound_crossings, declares the async
# groups through set_async_clock_groups (async_clock_groups.tcl) so the
# per-instance max-delay layer can take effect.
#
# cdc_max_delay_procs.tcl shares ::cdc_hier_prefix and ::cdc_clock_alias with
# this file, so one prefix setting drives both the generated max-delay replay
# and the constraint replay.
#
# A file that uses these procs guards against being sourced first:
#
#   if {[info procs cdc_is_block_top] eq ""} {
#       source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
#   }
################################################################################

if { ![info exists ::cdc_hier_prefix] } { set ::cdc_hier_prefix "" }
if { ![array exists ::cdc_clock_alias] } { array set ::cdc_clock_alias {} }
if { ![array exists ::cdc_reset_alias] } { array set ::cdc_reset_alias {} }
# Async-group registration: canonical (post-alias) domain name -> list of extra clock names
# that belong in that domain's group (generated clocks a child defines).
if { ![array exists ::cdc_domain_extra] } { array set ::cdc_domain_extra {} }
# Scenario the constraints are read for. "synth" (the default, nothing sets it) applies
# every IO delay; "functional" is the CDC/RDC sign-off run whose case-analysis files pin
# the DFT and strap ports, so those ports get no IO delay there.
if { ![info exists ::cdc_scenario] } { set ::cdc_scenario synth }
# Whether the synth scenario bounds the crossings (-allow_paths groups with default
# bounds plus the block's per-instance max-delay layer) or declares bare async groups.
if { ![info exists ::cdc_bound_crossings] } { set ::cdc_bound_crossings 1 }
# Clock-name pattern pairs that already carry another relationship (typically
# -logically_exclusive on muxed sources) and must stay out of the asynchronous
# declaration in the synth scenario; a block SDC sets it before its groups.
if { ![info exists ::cdc_async_exclude] } { set ::cdc_async_exclude {} }

# Directory holding this file, for the sibling async_clock_groups.tcl.
if { [info script] ne "" } {
    set ::cdc_hier_procs_dir [file dirname [file normalize [info script]]]
} elseif { [info exists ::env(GIT_ROOT)] } {
    set ::cdc_hier_procs_dir [file normalize $::env(GIT_ROOT)/flows/synth/constraints]
} else {
    error "cdc_hier_procs.tcl: cannot locate this file's directory; set GIT_ROOT"
}

# True when constraints are being applied at the block's own top (no re-anchoring).
proc cdc_is_block_top { } { return [expr { $::cdc_hier_prefix eq "" }] }

# True when the case-analysis files pin the DFT/strap ports (functional scenario).
proc cdc_ports_pinned { } { return [expr { $::cdc_scenario eq "functional" }] }

# IO delay for a port the functional scenario pins by case analysis: applied in every
# other scenario (synthesis, a DFT-mode sign-off run), skipped where the port is pinned.
proc cdc_pinned_port_delay { args } {
    if { [cdc_ports_pinned] } { return }
    {*}$args
}

# Prefix a block-relative hierarchical path. Identity at block top.
proc cdc_inst { inst } {
    if { $::cdc_hier_prefix eq "" } { return $inst }
    return "${::cdc_hier_prefix}$inst"
}

# Map block-local clock names onto the adopter's. Takes and returns a list, since a muxed
# domain resolves to several clocks.
proc cdc_clk { clks } {
    set out {}
    foreach c $clks {
        if { [info exists ::cdc_clock_alias($c)] } {
            lappend out $::cdc_clock_alias($c)
        } else {
            lappend out $c
        }
    }
    return $out
}

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

# Register extra clocks (generated clocks a block defines) into a canonical async domain.
# Both the domain name and the clock names go through the alias map, so children register
# with their local names and the parent's table lands them in the right group.
proc cdc_group_extra { domain clks } {
    set d [lindex [cdc_clk $domain] 0]
    if { ![info exists ::cdc_domain_extra($d)] } { set ::cdc_domain_extra($d) {} }
    foreach c [cdc_clk $clks] {
        if { [lsearch -exact $::cdc_domain_extra($d) $c] < 0 } {
            lappend ::cdc_domain_extra($d) $c
        }
    }
}

# Declare the asynchronous clock groups over the given canonical domain names, once.
# Each group = the domain clock itself plus everything registered via cdc_group_extra,
# filtered down to clocks that actually exist in this session. Groups with no existing
# clocks are dropped with an INFO, which lets one domain list serve full-hierarchy,
# reduced and per-block configurations.
#
# Emission follows the scenario. The functional (sign-off) run gets one bare
# set_clock_groups -asynchronous, as does a synth run with ::cdc_bound_crossings 0. The
# bounded synth run goes through set_async_clock_groups, which declares the groups with
# -allow_paths and bounds every inter-group pair, since a bare async declaration would
# outrank the per-instance CDC max-delay exceptions.
proc cdc_apply_async_groups { domains } {
    set groups {}
    foreach d $domains {
        set want [list $d]
        if { [info exists ::cdc_domain_extra($d)] } {
            foreach c $::cdc_domain_extra($d) { lappend want $c }
        }
        set have {}
        foreach c $want {
            if { [sizeof_collection [get_clocks -quiet $c]] > 0 } {
                if { [lsearch -exact $have $c] < 0 } { lappend have $c }
            }
        }
        if { [llength $have] > 0 } {
            lappend groups $have
        } else {
            puts "INFO: cdc_hier: async domain '$d' has no defined clocks - group dropped"
        }
    }
    if { [llength $groups] < 2 } {
        puts "WARNING: cdc_hier: fewer than 2 non-empty async groups - set_clock_groups skipped"
        return
    }
    if { $::cdc_scenario eq "synth" && $::cdc_bound_crossings } {
        if { [info procs set_async_clock_groups] eq "" } {
            source [file join $::cdc_hier_procs_dir async_clock_groups.tcl]
        }
        puts "INFO: cdc_hier: applying async clock groups with -allow_paths and default bounds: $groups"
        set_async_clock_groups $groups -exclude $::cdc_async_exclude
        return
    }
    set cmd [list set_clock_groups -asynchronous]
    foreach g $groups { lappend cmd -group $g }
    puts "INFO: cdc_hier: applying async clock groups: $groups"
    {*}$cmd
}

# ---------------------------------------------------------------------------------------
# Per-child scoping for a parent aggregator (hw/sys/smu/cdc/smu.cdc_rdc.tcl):
#
#   cdc_begin_block u_smc/ {SMCCLK SMUCLK} {JTAG_RESET {}}
#   source hw/sys/smc/cdc/smc.cdc_rdc.tcl
#   cdc_end_block
#
# clock_alias / reset_alias are flat {from to from to ...} lists. Nesting is not
# supported (one level of begin/end at a time).
# ---------------------------------------------------------------------------------------
proc cdc_begin_block { prefix { clock_alias {} } { reset_alias {} } } {
    if { $::cdc_hier_prefix ne "" } {
        puts "WARNING: cdc_hier: cdc_begin_block '$prefix' while prefix '$::cdc_hier_prefix' active - nesting unsupported"
    }
    set ::cdc_hier_prefix $prefix
    array unset ::cdc_clock_alias
    array set ::cdc_clock_alias $clock_alias
    array unset ::cdc_reset_alias
    array set ::cdc_reset_alias $reset_alias
    puts "INFO: cdc_hier: begin block prefix='$prefix' clock_alias={$clock_alias} reset_alias={$reset_alias}"
}

proc cdc_end_block { } {
    puts "INFO: cdc_hier: end block prefix='$::cdc_hier_prefix'"
    set ::cdc_hier_prefix ""
    array unset ::cdc_clock_alias
    array set ::cdc_clock_alias {}
    array unset ::cdc_reset_alias
    array set ::cdc_reset_alias {}
}

puts "INFO: cdc_hier_procs loaded (prefix='$::cdc_hier_prefix', scenario=$::cdc_scenario)"
