# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# Case analysis for the SEP block
#
# Hierarchy-reusable: port references go through cdc_port_or_pin (get_ports at the SEP
# top, gen_sep.u_sep/<port> instance pins at the SMU top), guarded so a non-matching
# struct-flattened pin warns instead of silently no-oping.

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
}

proc _sep_case { value pattern } {
    if { ![cdc_ports_pinned] } { return }
    set obj [cdc_port_or_pin $pattern]
    if { [sizeof_collection $obj] > 0 } {
        set_case_analysis $value $obj
    } else {
        puts "WARNING: sep_case_analysis: no object matches '$pattern' (prefix '$::cdc_hier_prefix') - skipped"
    }
}

# TODO: Create a separate DFT-mode CDC scenario with these set to 1 to get full coverage of the override reset path through the mux
_sep_case 0 {test_en_i}
_sep_case 0 {scan_rst_ni}

# JTAG reset overrides are quasi-static debug straps; pin off for functional CDC/RDC
_sep_case 0 {jtag_sep_reset_ctrl_i.ovrd*}
_sep_case 0 {jtag_sep_reset_ctrl_i.val*}

# Boot sequence done
_sep_case 1 {ext_boot_seq_done_i}

rename _sep_case {}
