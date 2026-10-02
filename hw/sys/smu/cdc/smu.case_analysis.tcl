# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
# Case analysis for the SMU top level.
#
# Only SMU top-PORT truth lives here; the subcomponent-internal pin stamps (e.g. the
# u_smc jtag_reset_ctrl_i.* debug overrides) come from the inherited child files
# (smc_case_analysis.tcl / sep_case_analysis.tcl re-anchored via cdc_port_or_pin) in
# hw/sys/smu/cdc/smu.cdc_rdc.tcl.

# Pin to the same functional/non-scan values the blocks use (test_en_i/scan_rst_ni = 0).
if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
}
if { [cdc_ports_pinned] } {
    set_case_analysis 0 [get_ports {test_en_i}]
    set_case_analysis 0 [get_ports {scan_rst_ni}]
    # DFX boot-sequence-done strap.
    set_case_analysis 1 [get_ports {ext_boot_seq_done_i}]
}
