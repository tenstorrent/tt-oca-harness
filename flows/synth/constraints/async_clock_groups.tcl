# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# async_clock_groups.tcl - async clock groups with default bounds
#
# Copy of the closed flow's global.async_clock_groups.tcl. Sourced by each
# hw/sys/<block>/synth/constraints.sdc in place of a bare set_clock_groups.
#
#   set_async_clock_groups <groups> [-exclude {{patA patB} ...}]
#                                   [-max_delay ps] [-min_delay ps]
#
# Declares the groups with -allow_paths so the CDC max_delay recipes can take
# effect, and applies a loose default bound to every inter-group clock pair so
# crossings without a specific recipe are bounded rather than failing.
#
# These two must stay together: -allow_paths on its own turns every
# unconstrained crossing into a violation.
#
# The bound is emitted per inter-group pair and never within a group. It is
# looser than any clock period here, so on a synchronous path it would override
# the real setup check and mask intra-domain failures - which is why this needs
# the group list and belongs beside the clock definitions.
#
# The per-instance recipes, set on pins, take precedence over this bound.
#
# The negative min_delay drops hold checking between async domains.
#
# -exclude names clock pairs that must not be declared asynchronous because
# another relationship already covers them, typically -logically_exclusive on
# muxed clock sources. A pair cannot carry both relationships.
#
# Groups are emitted pairwise, not as one N-group command, so an exclusion can
# suppress part of a single pair's cross product. Do not collapse it back: one
# N-group call cannot express the exclusion, and the non-excluded pairs would
# lose their async declaration - leaving them timed as synchronous rather than
# left alone.
################################################################################

# Time unit is picoseconds, matching the clock periods each block's
# constraints.sdc declares.
if { ![info exists ::CDC_DEFAULT_MAX_DELAY] } { set ::CDC_DEFAULT_MAX_DELAY 20000 } ;#  20 ns
if { ![info exists ::CDC_DEFAULT_MIN_DELAY] } { set ::CDC_DEFAULT_MIN_DELAY -20000 } ;# -20 ns

# Domain registration, for a block whose constraints are replayed at a parent level.
# A child registers the generated clocks it defines against a canonical domain name;
# cdc_apply_async_groups then emits one group per domain through the same path as
# set_async_clock_groups, so a hierarchical run keeps `-allow_paths` and the default
# bounds. Without them a CDC crossing becomes a false path and the per-instance bounds
# in *_cdc_max_delay.tcl are masked, which is the opposite of what the bounds are for.
if { ![array exists ::cdc_domain_extra] } { array set ::cdc_domain_extra {} }

# cdc_clk maps a block-local clock name onto the adopter's. Defined here as an identity
# when no adopter hook file has been sourced yet, so this file stands alone in the open
# flow; cdc_max_delay_procs.tcl and hier_reuse_procs.tcl define the same proc.
if { [info procs cdc_clk] eq "" } {
    if { ![info exists ::cdc_hier_prefix] } { set ::cdc_hier_prefix "" }
    if { ![array exists ::cdc_clock_alias] } { array set ::cdc_clock_alias {} }
    proc cdc_clk { clks } {
        set out {}
        foreach c $clks {
            if { [info exists ::cdc_clock_alias($c)] } {
                foreach m $::cdc_clock_alias($c) { lappend out $m }
            } else {
                lappend out $c
            }
        }
        return $out
    }
}

proc cdc_group_extra { domain clks } {
    set d [lindex [cdc_clk $domain] 0]
    if { ![info exists ::cdc_domain_extra($d)] } { set ::cdc_domain_extra($d) {} }
    foreach c [cdc_clk $clks] {
        if { [lsearch -exact $::cdc_domain_extra($d) $c] < 0 } {
            lappend ::cdc_domain_extra($d) $c
        }
    }
}

# One group per domain: the domain clock plus everything registered against it. Groups
# matching no clock are dropped by set_async_clock_groups, so one domain list serves a
# full-hierarchy run, a reduced configuration and a per-block run alike.
proc cdc_apply_async_groups { domains args } {
    set groups {}
    foreach d $domains {
        set want [list $d]
        if { [info exists ::cdc_domain_extra($d)] } {
            foreach c $::cdc_domain_extra($d) { lappend want $c }
        }
        lappend groups $want
    }
    set_async_clock_groups $groups {*}$args
}

# Is this ordered clock pair covered by an exclusion? Patterns match either way
# round, so a caller need not list a pair twice.
proc acg_excluded { a b exclude } {
    foreach pr $exclude {
        lassign $pr pa pb
        if {
            ([string match $pa $a] && [string match $pb $b]) ||
            ([string match $pb $a] && [string match $pa $b])
        } { return 1 }
    }
    return 0
}

# groups: list of clock-name lists, one per async domain; entries may be globs.
#         Groups matching no clock are dropped, so one list serves partial (SAM)
#         and full runs.
proc set_async_clock_groups { groups args } {
    array set opt [list -max_delay $::CDC_DEFAULT_MAX_DELAY \
        -min_delay $::CDC_DEFAULT_MIN_DELAY \
        -exclude {}]
    array set opt $args
    set max_delay $opt(-max_delay)
    set min_delay $opt(-min_delay)
    set exclude $opt(-exclude)

    set names {}
    foreach g $groups {
        set c [get_clocks $g -quiet]
        if { [sizeof_collection $c] == 0 } {
            puts "INFO: async_clock_groups: group {$g} matched no clock, dropped"
            continue
        }
        lappend names [get_object_name $c]
    }
    set ng [llength $names]
    if { $ng < 2 } {
        puts "WARNING: async_clock_groups: fewer than two groups resolved -\
              no asynchronous relationship declared"
        return
    }

    set n_grp 0; set n_split 0
    for { set i 0 } { $i < $ng } { incr i } {
        for { set j [expr { $i + 1 }] } { $j < $ng } { incr j } {
            set gi [lindex $names $i]
            set gj [lindex $names $j]

            # Split each side into the clocks that participate in an exclusion
            # with the other side, and the rest.
            set xi {}; set ri {}
            foreach a $gi {
                set hit 0
                foreach b $gj { if { [acg_excluded $a $b $exclude] } { set hit 1; break } }
                if { $hit } { lappend xi $a } else { lappend ri $a }
            }
            set xj {}; set rj {}
            foreach b $gj {
                set hit 0
                foreach a $gi { if { [acg_excluded $a $b $exclude] } { set hit 1; break } }
                if { $hit } { lappend xj $b } else { lappend rj $b }
            }

            if { ![llength $xi] || ![llength $xj] } {
                set_clock_groups -asynchronous -allow_paths \
                    -group [get_clocks $gi] -group [get_clocks $gj]
                incr n_grp
            } else {
                if { [llength $ri] } {
                    set_clock_groups -asynchronous -allow_paths \
                        -group [get_clocks $ri] -group [get_clocks $gj]
                    incr n_grp
                }
                if { [llength $rj] } {
                    set_clock_groups -asynchronous -allow_paths \
                        -group [get_clocks $xi] -group [get_clocks $rj]
                    incr n_grp
                }
                incr n_split
                puts "INFO: async_clock_groups: exclusion split on pair\
                      ([lindex $gi 0].. x [lindex $gj 0]..):\
                      [llength $xi]x[llength $xj] clock pairs left to their\
                      existing relationship"
            }
        }
    }
    puts "INFO: async_clock_groups: $ng groups, $n_grp set_clock_groups calls\
          with -allow_paths ($n_split pairs split by -exclude)"

    # One clock to one clock rather than collection to collection, so each
    # exception is individually reportable and one pair can be returned without
    # unpicking a group. Both directions: -from A -to B does not cover B -> A.
    set n 0; set n_skip 0
    for { set i 0 } { $i < $ng } { incr i } {
        for { set j 0 } { $j < $ng } { incr j } {
            if { $i == $j } { continue }
            foreach src [lindex $names $i] {
                set from [get_clocks $src]
                foreach dst [lindex $names $j] {
                    if { [acg_excluded $src $dst $exclude] } { incr n_skip; continue }
                    set to [get_clocks $dst]
                    set_max_delay $max_delay -ignore_clock_latency -from $from -to $to
                    set_min_delay $min_delay -ignore_clock_latency -from $from -to $to
                    incr n
                }
            }
        }
    }
    puts "INFO: async_clock_groups: default bounds on $n ordered clock pairs,\
          $n_skip skipped by -exclude (max $max_delay ps, min $min_delay ps)"
}
