# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# cdc_max_delay_procs.tcl - one procedure per CDC element type
#
# Each proc takes an instance path and the clock domain(s) it crosses, and emits
# the max_delay exceptions for that element. Subsystem files call them with
# explicit paths - nothing is discovered, no clock is inferred, no design or
# instance name is pattern-matched.
#
#   set_cdc_max_delay_prim_sync3        <inst> <dst_clk> [delay]
#   set_cdc_max_delay_prim_fifo_async   <inst> <wr_clk> <rd_clk> [delay]
#   ... one per type, see below
#
# Sourced by each hw/sys/<block>/synth/constraints.sdc before that block's
# <block>_cdc_max_delay.tcl. This is a copy of the closed flow's
# global.cdc_max_delay_procs.tcl; when a new element type is added there, add it
# here too or the block's generated file will fail on an unknown command.
#
# Requires the block's async clock groups to be declared with -allow_paths
# (set_async_clock_groups); a bare set_clock_groups -asynchronous silently
# outranks every max_delay here. Any crossing not listed by a subsystem file is
# still bounded by the default 20 ns from that same call - these procs are for
# tightening the ones that matter.
#
# Synchronizer procs target the WRAPPER's data input port (prim_sync3/i_d), not
# the leaf flops inside it. One wrapper pin covers the whole bus, so SMC needs
# ~365 calls rather than the ~1200 the leaf cells would take.
################################################################################

puts "INFO: Loading CDC max_delay procs"

array set ::cdc_stats {}
set ::cdc_to_pins {}
proc cdc_stat { k { n 1 } } {
    if { ![info exists ::cdc_stats($k)] } { set ::cdc_stats($k) 0 }
    incr ::cdc_stats($k) $n
}
proc cdc_info { m } { puts "INFO: cdc_max_delay: $m" }
proc cdc_warn { m } { cdc_stat warnings; puts "WARNING: cdc_max_delay: $m" }

################################################################################
# ADOPTER HOOKS
################################################################################
# Both default to no-ops: an empty prefix and no aliases reproduce the shipped
# behaviour exactly. They exist so a generated file can be reused against a
# design that instantiates the block somewhere else, or drives it from
# differently named clocks, without regenerating.
#
#   set ::cdc_hier_prefix        u_chiplet/u_mgmt/u_smc/
#   set ::cdc_clock_alias(SMCCLK) MY_SYS_CLK
#
# They do NOT cover a reconfigured block: if parameters change which CDC
# elements exist, regenerate instead.
if { ![info exists ::cdc_hier_prefix] } { set ::cdc_hier_prefix "" }
if { ![array exists ::cdc_clock_alias] } { array set ::cdc_clock_alias {} }

proc cdc_inst { inst } {
    if { $::cdc_hier_prefix eq "" } { return $inst }
    return "${::cdc_hier_prefix}$inst"
}

# Map clock names onto the adopter's. Takes and returns a list, since a muxed
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

################################################################################
# HELPERS
################################################################################

# Period of a named clock. Prefer the clock object, since generated and muxed
# clocks have no entry in the block's clock_periods array.
# A generated clock has no `period` attribute of its own - the period is implied
# by its master and divide factor, and this tool exposes no way to read it back.
# Set ::cdc_clock_period(<name>) for those; the subsystem file knows the divide
# ratio because it wrote the create_generated_clock.
proc cdc_period { clk } {
    if { [info exists ::cdc_clock_period($clk)] } { return $::cdc_clock_period($clk) }
    set c [get_clocks [cdc_clk $clk] -quiet]
    if { [sizeof_collection $c] > 0 } {
        set p [get_attribute -quiet $c period]
        if { $p ne "" && $p > 0 } { return $p }
    }
    if { [info exists ::clock_periods(${clk}_PERIOD)] } {
        return $::clock_periods(${clk}_PERIOD)
    }
    cdc_warn "no period for clock '$clk' - set ::cdc_clock_period($clk) to fix"
    return 0
}

proc cdc_min_period { args } {
    set best 0
    foreach c $args {
        set p [cdc_period $c]
        if { $p > 0 && ($best == 0 || $p < $best) } { set best $p }
    }
    return $best
}

# Emit one exception. Warns and does nothing if either endpoint is empty, which
# is the only failure mode left: a wrong instance path or a renamed signal.
proc cdc_emit { tag dly mode from to } {
    if { $dly <= 0 } { cdc_warn "$tag: no delay resolved, skipped"; return }
    # mode `to` intentionally has no -from; only the other modes need a source.
    if { $mode ne "to" && [sizeof_collection $from] == 0 } {
        cdc_warn "$tag: source empty"; return
    }
    # mode `through_only` bounds a net segment, so it has no endpoint either.
    if { $mode ne "through_only" && [sizeof_collection $to] == 0 } {
        cdc_warn "$tag: destination empty"; return
    }
    switch -- $mode {
        to {
            set_max_delay $dly -ignore_clock_latency -to $to
            set ::cdc_to_pins [add_to_collection $::cdc_to_pins $to]
        }
        from { set_max_delay $dly -ignore_clock_latency -from $from -to $to }
        through { set_max_delay $dly -ignore_clock_latency -through $from -to $to }
        through_only { set_max_delay $dly -ignore_clock_latency -through $from }
    }
    cdc_stat exceptions
    cdc_info [format "%-34s %8.1f ps  %s" $tag $dly $mode]
}

# A clock argument may be a LIST of clock names - a muxed domain such as avs_clk
# is attributed several clocks at once. The tightest period wins, so the bound is
# never silently loose.
#
# Synchronizer input: half the capturing clock period.
proc cdc_sync_delay { dst_clk delay } {
    if { $delay ne "" } { return $delay }
    return [expr { 0.5 * [cdc_min_period {*}$dst_clk] }]
}
# Protocol-protected data. Not a metastability bound - the payload never passes
# through a synchronizer. The pointer does, and the read side only looks at an
# entry once the pointer has crossed, so the real requirement is
# SYNC_STAGES x T_dst (3 for cdc_fifo_gray, 2 for prim_fifo_async). One period is
# deliberately conservative; raise to 2.0 if wide payloads will not close, which
# is still inside the guarantee with a cycle spare. Miss the bound and the
# consumer samples the entry's previous contents - silent data corruption, not a
# timing violation.
proc cdc_data_delay { dst_clk delay } {
    if { $delay ne "" } { return $delay }
    return [cdc_min_period {*}$dst_clk]
}

################################################################################
# SYNCHRONIZER WRAPPERS
################################################################################
# Bound the wrapper's data input. mode `to` has no -from, so it also catches
# same-domain paths into that pin; those are bare flop-to-flop hops and meet the
# bound trivially.

proc set_cdc_max_delay_prim_sync2 { inst dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "prim_sync2 $inst" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/i_d" -quiet]
}
proc set_cdc_max_delay_prim_sync3 { inst dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "prim_sync3 $inst" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/i_d" -quiet]
}
proc set_cdc_max_delay_prim_sync4 { inst dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "prim_sync4 $inst" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/i_d" -quiet]
}

# hw/common/sync.sv, the pulp shim used by the common_cells CDC library.
proc set_cdc_max_delay_sync { inst dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "sync $inst" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/serial_i" -quiet]
}

# Reset-deassertion synchronizer; the async input is rst_n.
proc set_cdc_max_delay_prim_sync_reset { inst dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "prim_sync_reset $inst" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/rst_n" -quiet]
}

# Pulse crossing: toggle in the source domain, 3-stage sync in the destination.
proc set_cdc_max_delay_prim_sync3_pulse { inst dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "prim_sync3_pulse $inst" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/i_dest/toggle" -quiet]
}

################################################################################
# TWO-PHASE HANDSHAKE CROSSINGS
################################################################################

# pulp cdc_2phase / cdc_2phase_clearable. Both halves hold raw inline flops
# rather than a sync wrapper, so there is no port to constrain - the crossing is
# the async_req / async_ack / async_data nets between them, which carry
# dont_touch and survive to routing.
#
# min(T_src, T_dst) rather than T_dst: the handshake runs in both directions, so
# the tighter of the two domains governs. This is the module header's own stated
# requirement, not a choice made here.
#
# cdc_fifo_2phase needs no entry of its own - it instantiates cdc_2phase twice,
# and the generator finds those inner instances by path.
proc set_cdc_max_delay_cdc_2phase { inst src_clk dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set dly $delay
    if { $dly eq "" } { set dly [cdc_min_period {*}$src_clk {*}$dst_clk] }
    cdc_emit "cdc_2phase $inst" $dly through_only \
        [get_nets "$inst/async_*" -quiet] {}
}

################################################################################
# GRAY-POINTER ASYNC FIFOS
################################################################################
# Pointers are constrained at the synchronizer wrapper inputs; the storage array
# is a protocol-protected data path and gets a full destination period.

proc set_cdc_max_delay_prim_fifo_async { inst wr_clk rd_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "prim_fifo_async $inst"
    cdc_emit "$t wptr" [cdc_sync_delay $rd_clk $delay] to \
        {} [get_pins "$inst/sync_wptr/d_i" -quiet]
    cdc_emit "$t rptr" [cdc_sync_delay $wr_clk $delay] to \
        {} [get_pins "$inst/sync_rptr/d_i" -quiet]
    cdc_emit "$t data" [cdc_data_delay $rd_clk $delay] from \
        [get_pins "$inst/storage*_reg*/Q*" -quiet] [get_clocks [cdc_clk $rd_clk]]
}

proc set_cdc_max_delay_avsbus_async_fifo { inst wr_clk rd_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "avsbus_async_fifo $inst"
    cdc_emit "$t data" [cdc_data_delay $rd_clk $delay] from \
        [get_pins "$inst/fifo_array*_reg*/Q*" -quiet] [get_clocks [cdc_clk $rd_clk]]
    # Pointer syncs are prim_sync3 arrays; constrain each wrapper by name.
    foreach {sync dst} [list wr_ptr_gray_sync_to_rd_clk $rd_clk \
        rd_ptr_gray_sync_to_wr_clk $wr_clk] {
        cdc_emit "$t $sync" [cdc_sync_delay $dst $delay] to \
            {} [get_pins "$inst/$sync*/i_d" -quiet]
    }
}

# pulp cdc_fifo_gray / cdc_fifo_gray_clearable: self-contained, both clocks on
# the wrapper. Pointer syncs are `sync` shims inside i_src / i_dst.
#
# Generate scopes are separated by `.`, not `/` - the instance is
# gen_sync[0].i_sync - so the glob must not put a slash before i_sync.
proc set_cdc_max_delay_cdc_fifo_gray { inst src_clk dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "cdc_fifo_gray $inst"
    cdc_emit "$t wptr" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/i_dst/gen_sync*i_sync/serial_i" -quiet]
    cdc_emit "$t rptr" [cdc_sync_delay $src_clk $delay] to \
        {} [get_pins "$inst/i_src/gen_sync*i_sync/serial_i" -quiet]
    cdc_emit "$t data" [cdc_data_delay $dst_clk $delay] from \
        [get_pins "$inst/i_src/data_q_reg*/Q*" -quiet] [get_clocks [cdc_clk $dst_clk]]
}

################################################################################
# BUS CDC
################################################################################
# axi_cdc splits into i_axi_cdc_src / i_axi_cdc_dst, each holding
# cdc_fifo_gray_src / _dst halves directly rather than the self-contained
# wrapper. Only the _src half has a data_q register, so the i_cdc_fifo_gray_src_*
# glob picks the sending side. aw/w/ar travel src->dst, b/r travel dst->src.
proc set_cdc_max_delay_axi_cdc { inst src_clk dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "axi_cdc $inst"
    cdc_emit "$t data src2dst" [cdc_data_delay $dst_clk $delay] from \
        [get_pins "$inst/i_axi_cdc_src/i_cdc_fifo_gray_src_*/data_q_reg*/Q*" -quiet] \
        [get_clocks [cdc_clk $dst_clk]]
    cdc_emit "$t data dst2src" [cdc_data_delay $src_clk $delay] from \
        [get_pins "$inst/i_axi_cdc_dst/i_cdc_fifo_gray_src_*/data_q_reg*/Q*" -quiet] \
        [get_clocks [cdc_clk $src_clk]]
    foreach {half dst} [list i_axi_cdc_src $dst_clk i_axi_cdc_dst $src_clk] {
        cdc_emit "$t $half ptr" [cdc_sync_delay $dst $delay] to \
            {} [get_pins "$inst/$half/*/gen_sync*i_sync/serial_i" -quiet]
    }
}

################################################################################
# HANDSHAKE DATA CROSSINGS
################################################################################

proc set_cdc_max_delay_prim_sync_data_autohs { inst src_clk dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "prim_sync_data_autohs $inst"
    cdc_emit "$t req" [cdc_sync_delay $dst_clk $delay] to \
        {} [get_pins "$inst/*sync_req_toggle/d_i" -quiet]
    cdc_emit "$t ack" [cdc_sync_delay $src_clk $delay] to \
        {} [get_pins "$inst/*sync_ack_toggle/d_i" -quiet]
    # -to the destination clock, not clk2_val_reg/D: before mapping, flop inputs
    # are GTECH `next_state` pins, so any /D pattern resolves empty here.
    cdc_emit "$t data" [cdc_data_delay $dst_clk $delay] from \
        [get_pins "$inst/clk1_val_reg*/Q*" -quiet] [get_clocks [cdc_clk $dst_clk]]
    if { [sizeof_collection [get_cells "$inst/gen_depth_2*" -quiet]] > 0 } {
        cdc_warn "$t uses a 2-stage synchronizer (DEPTH=2); 3 is recommended"
    }
}

# prim_reg_cdc: src_q / txn_bits_q captured in the source domain, read in the
# destination under a prim_pulse_sync handshake.
proc set_cdc_max_delay_prim_reg_cdc { inst src_clk dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "prim_reg_cdc $inst"
    set from [get_pins "$inst/src_q_reg*/Q*" -quiet]
    set txn [get_pins "$inst/txn_bits_q_reg*/Q*" -quiet]
    if { [sizeof_collection $txn] } { set from [add_to_collection $from $txn] }
    cdc_emit "$t data" [cdc_data_delay $dst_clk $delay] from $from [get_clocks [cdc_clk $dst_clk]]
}

# Feedthrough as configured in this design (DataSrc2Dst=0, DataReg=0): both
# endpoints are outside the cell, so the port is a -through point, and the
# capturing clock is clk_src_i because data flows dst->src.
proc set_cdc_max_delay_prim_sync_reqack_data { inst src_clk dst_clk { delay {} } } {
    set inst [cdc_inst $inst]
    cdc_emit "prim_sync_reqack_data $inst" [cdc_data_delay $src_clk $delay] through \
        [get_pins "$inst/data_i*" -quiet] [get_clocks [cdc_clk $src_clk]]
}

################################################################################
# FOREIGN CDC ELEMENTS
################################################################################

# Rocket/Chisel AsyncQueue. Payload crosses combinationally on the Sink's
# io_async_mem_0_* inputs; pointers and the valid/reset handshake are
# AsyncValidSync chains that bottom out in prim cells.
proc set_cdc_max_delay_rocket_async_queue { sink_inst dst_clk { delay {} } } {
    set sink_inst [cdc_inst $sink_inst]
    cdc_emit "rocket_async_queue $sink_inst" [cdc_data_delay $dst_clk $delay] through \
        [get_pins "$sink_inst/io_async_mem_0_*" -quiet] [get_clocks [cdc_clk $dst_clk]]
}

# VeeR EL2 DMI. reg_wr_data / reg_wr_addr come straight out of the TCK-domain TAP
# gated by an edge-detected enable; the enable itself is an inline 3-deep shift
# register rather than a prim cell.
proc set_cdc_max_delay_dmi_wrapper { inst core_clk { delay {} } } {
    set inst [cdc_inst $inst]
    set t "dmi_wrapper $inst"
    cdc_emit "$t enable" [cdc_sync_delay $core_clk $delay] to \
        {} [get_pins "$inst/i_dmi_jtag_to_core_sync/rd_en" -quiet]
    cdc_emit "$t data" [cdc_data_delay $core_clk $delay] from \
        [get_pins "$inst/i_jtag_tap/dr_reg*/Q*" -quiet] [get_clocks [cdc_clk $core_clk]]
}

################################################################################
# Hand the synchronizer paths that start at a primary input back to the default
# bound. A synchronizer input reachable from a port carries that port's
# set_input_delay - a budget figure, not real logic - which on its own can exceed
# 0.5 x T_dst and make the path unmeetable at this level. Only the parent block
# sees both endpoints, so there is nothing to tighten here.
#
# -from ports -to pins outranks the bare -to, so this wins for port-driven paths
# and leaves register-driven ones on the tight bound.
proc cdc_relax_primary_inputs { } {
    if { ![info exists ::CDC_DEFAULT_MAX_DELAY] } { set ::CDC_DEFAULT_MAX_DELAY 20000 }
    if { ![info exists ::CDC_DEFAULT_MIN_DELAY] } { set ::CDC_DEFAULT_MIN_DELAY -20000 }
    if { [sizeof_collection $::cdc_to_pins] == 0 } { return }
    set ports [all_inputs]
    if { [sizeof_collection $ports] == 0 } { return }
    set_max_delay $::CDC_DEFAULT_MAX_DELAY -ignore_clock_latency -from $ports -to $::cdc_to_pins
    set_min_delay $::CDC_DEFAULT_MIN_DELAY -ignore_clock_latency -from $ports -to $::cdc_to_pins
    cdc_info "primary-input paths into [sizeof_collection $::cdc_to_pins] sync pins\
              held at the default bound ($::CDC_DEFAULT_MAX_DELAY ps)"
}

proc cdc_max_delay_summary { } {
    cdc_relax_primary_inputs
    foreach k {exceptions warnings} {
        if { ![info exists ::cdc_stats($k)] } { set ::cdc_stats($k) 0 }
    }
    cdc_info "SUMMARY $::cdc_stats(exceptions) exceptions, $::cdc_stats(warnings) warnings"
    if { $::cdc_stats(exceptions) == 0 } {
        cdc_warn "ZERO exceptions applied - treat as a setup failure"
    }
}

puts "INFO: CDC max_delay procs loaded."
