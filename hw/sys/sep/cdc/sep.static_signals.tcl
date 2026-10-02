# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
########################################################
# Quasi Static Signals
########################################################
# Hierarchy-reusable: port references go through cdc_port_or_pin, `-hier` globs are
# level-independent. See flows/synth/constraints/hier_reuse_procs.tcl.

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
}

proc _sep_static_port { pattern } {
    set obj [cdc_port_or_pin $pattern]
    if { [sizeof_collection $obj] > 0 } {
        create_static -name $obj
    } else {
        puts "WARNING: sep_static_signals: no object matches '$pattern' (prefix '$::cdc_hier_prefix') - skipped"
    }
}

# TEST_EN strap, captured once at boot (secure test mode request)
_sep_static_port {secure_tm_req_i}

# SMC address configuration, programmed during boot
_sep_static_port {smc_global_base_addr_i*}
_sep_static_port {smc_region_size_i*}

# CPU configuration sampled at reset
_sep_static_port {jtag_id_i*}

rename _sep_static_port {}

# Entropy static signals below are non-functional; entropy_source is currently blackboxed.
# Entropy sample-clock source/divide config, programmed before generators are enabled
set sclk_config [get_nets -hier -quiet {*SAMPLE_CLK_DIVIDE.value* *SAMPLE_CLK_SELECT.value*}]
if { [sizeof_collection $sclk_config] > 0 } {
    create_static -name $sclk_config
}

# Entropy debug monitor select, chooses which internal signal to observe off-chip
set dbg_mon_select [get_nets -hier -quiet {*DEBUG_CTRL.SELECT_SIGNAL.value* *DEBUG_CTRL.SELECT_FREQ_DIV.value*}]
if { [sizeof_collection $dbg_mon_select] > 0 } {
    create_static -name $dbg_mon_select
}

# EL2 JTAG reset-vector TDR, must not change during live SEPCLK operation
set rst_vec_tdr_pins [get_pins -quiet [cdc_inst "u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper/i_jtag_tap/rst_vec_tdr/Q*"]]
if { [sizeof_collection $rst_vec_tdr_pins] > 0 } {
    create_static -name $rst_vec_tdr_pins
} else {
    puts "WARNING: sep_static_signals: rst_vec_tdr pins not found - quasi-static stamp skipped"
}
