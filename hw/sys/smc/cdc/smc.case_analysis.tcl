# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
# Case analysis for the SMC block
#
# Hierarchy-reusable: port references go through cdc_port_or_pin (get_ports at the SMC
# top, u_smc/<port> instance pins at the SMU top). Struct-flattened ports can glob
# differently as pins, so each stamp is guarded and warns instead of silently no-oping.

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
}

proc _smc_case { value pattern } {
    if { ![cdc_ports_pinned] } { return }
    set obj [cdc_port_or_pin $pattern]
    if { [sizeof_collection $obj] > 0 } {
        set_case_analysis $value $obj
    } else {
        puts "WARNING: smc_case_analysis: no object matches '$pattern' (prefix '$::cdc_hier_prefix') - skipped"
    }
}

# TODO: Create a separate DFT-mode CDC scenario with these set to 1 to get full coverage of the override reset path through the mux
_smc_case 0 {test_en_i}
_smc_case 0 {scan_rst_ni}
# JTAG reset overrides are quasi-static debug strapping; pin them low for RDC
_smc_case 0 {jtag_reset_ctrl_i.ovrd*}
_smc_case 0 {jtag_reset_ctrl_i.val*}
_smc_case 0 {tdr_dbg_ctrl_clock_stop_en_i}

_smc_case 1 {ext_boot_seq_done_i}

rename _smc_case {}

# GPIO rst_cold_ni: used only as a combinational mux select inside gpio.sv
# (not as a flop reset — that role is rst_primary_ni). During functional mode
# cold reset is deasserted, so the if(~rst_cold_ni) branch is dead and SMCCLK
# should not propagate onto lsio_pad2core_data_o through this path.
set_case_analysis 1 [get_pins -hier *u_gpio_interface/rst_cold_ni]
