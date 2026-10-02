# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# smc.dfd_debug_bus_mux.tcl
#
# CDC constraints for the DFD debug bus mux (`tt_debug_bus_mux`, instantiated as
# `gen_dbm_l2[*]/u_debug_bus_mux_l2` and `gen_dbm_l3[*]/u_debug_bus_mux_l3` under
# `u_smc_base/u_internal_regs/u_smc_dfd_wrap`).
#
# Design intent — observation mux, not an async mixing point:
#   - Sixteen lanes; each lane is already synchronized into its observation
#     context before reaching the mux.
#   - Lane select (`mux_sel_q[lane]`) comes from DBM CSR `DbgMuxSelCsr.MuxselsegN`
#     when `enable_set_sel = id_match & (enable_mode == 2'b01)`.
#   - During an active debug capture session the select is held stable (software
#     does not reprogram it mid-session).
#   - `debug_bus_ff` on `clk_smc_i` registers the selected lane.
#
# Only one lane is electrically meaningful at the mux output at a time, so
# multi-domain reconvergence reported at `debug_mux_out[*]` is a tooling artifact,
# not a functional CDC hazard between unrelated async sources.
################################################################################

puts "INFO: Loading DFD debug bus mux CDC constraints"

set dbm_cells [get_cells -hier -filter {ref_name =~ tt_debug_bus_mux*} -quiet]
set dbm_input_pins [get_pins -of_objects $dbm_cells \
    -filter {name =~ debug_signals_in*} \
    -quiet]

if { [sizeof_collection $dbm_input_pins] > 0 } {
    cdc_conv_ignore_among $dbm_input_pins
    puts "INFO: Configured cdc_convergence ignore for [sizeof_collection $dbm_input_pins] tt_debug_bus_mux debug_signals_in pins"
} else {
    puts "WARNING: Found no tt_debug_bus_mux debug_signals_in pins -- check hierarchy"
}

# debug_mux_out is an internal net of tt_debug_bus_mux; register it per cell as a
# convergence ignore-at point (many-to-one observation fan-in, one lane selected at a time).
set dbm_out_nets [list]
foreach_in_collection c $dbm_cells {
    set n [get_nets -quiet "[get_object_name $c]/debug_mux_out*"]
    if {[sizeof_collection $n] > 0} {
        lappend dbm_out_nets {*}[get_object_name $n]
    }
}
if { [llength $dbm_out_nets] > 0 } {
    cdc_conv_ignore_at $dbm_out_nets
    puts "INFO: Contributed [llength $dbm_out_nets] tt_debug_bus_mux debug_mux_out nets as convergence ignore-at points"
} else {
    puts "WARNING: Found no tt_debug_bus_mux debug_mux_out nets -- check hierarchy"
}

puts "INFO: DFD debug bus mux CDC constraints loaded."
