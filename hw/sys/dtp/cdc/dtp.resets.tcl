# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# dtp.resets.tcl -- DTP reset declarations (CDC + RDC)
#
# Sourced by the DTP entry (cdc/dtp.cdc_rdc.tcl) and by the SMU flat run
# (hw/sys/smu/cdc/smu.cdc_rdc.tcl, prefix u_dtp/).
#
# Reset declarations use VC Static X-2025.06 syntax:
#   create_reset -name <n> -sense low <objects>
#   create_generated_reset -name <n> -sense low -master_reset <name_string> <objects>
# Note: -master_reset takes the NAME STRING of a prior create_reset/create_generated_reset,
# not a collection from get_ports/get_nets. declare_reset (Spyglass) is not supported.
#
# Hierarchy-reusable: the two primary port resets go through cdc_create_port_reset (skipped
# at the SMU top, where ::cdc_reset_alias maps rst_n_i -> PRIMARY_RESET_N_SMC_CLK and
# pwr_on_rst_ni -> POWERGOOD_STABLE_N); the derived-reset nets re-anchor through cdc_inst,
# with existence guards so configuration differences (absent generate branches) warn
# instead of erroring; -master_reset name strings map through cdc_rst.

if { [info procs cdc_create_port_reset] eq "" } {
    source $::env(GIT_ROOT)/flows/cdc/vc_procs.tcl
}

#=======================================================================================================================
# 0. RESET DECLARATIONS
#    create_reset declares the two primary input resets.
#    create_generated_reset declares derived resets in the JTAG hierarchy so the tool
#    can properly model reset domain boundaries and detect RDC_CORRUPT violations.
#=======================================================================================================================
cdc_create_port_reset rst_n_i "rst_n_i" -sense low
cdc_create_port_reset pwr_on_rst_ni "pwr_on_rst_ni" -sense low

# create_generated_reset on a DTP-internal net, re-anchored and guarded.
proc _dtp_gen_reset { name sense master net } {
    set obj [get_nets -quiet [cdc_inst $net]]
    if { [sizeof_collection $obj] > 0 } {
        create_generated_reset -name $name -sense $sense -master_reset [cdc_rst $master] $obj
    } else {
        puts "WARNING: dtp.resets: no net matches '[cdc_inst $net]' - reset '$name' skipped"
    }
}

# TRST_N gated with pwr_on_rst_ni: the effective JTAG subsystem reset.
#
# Block top: a generated child of pwr_on_rst_ni.
# Parent (SMU flat) runs: declared as its OWN reset. There pwr_on_rst_ni aliases to
# POWERGOOD_STABLE_N, which carries "-to_clock ... JTAG_TCK" assertion sequences (SMC
# smc.resets.tcl, SEP sep.resets.tcl: TCK has no edges while power-good is low). A generated
# child would inherit those sequences and prune every TRST-sourced RDC crossing into a
# TCK-clocked flop. TRST asserts from the pad with TCK running, so that pruning is not valid.
# The only true ordering is kept explicitly: power-good asserting forces trst_n_combined low
# through the AND gate, so POWERGOOD -> trst_n_combined crossings stay pruned.
if { [cdc_is_block_top] } {
    _dtp_gen_reset trst_n_combined low pwr_on_rst_ni {u_jtag_intf_unit/u_jtag_ptap/u_trst_n_and/out_o[0]}
} else {
    set _trst_obj [get_nets -quiet [cdc_inst {u_jtag_intf_unit/u_jtag_ptap/u_trst_n_and/out_o[0]}]]
    if { [sizeof_collection $_trst_obj] > 0 } {
        create_reset -name trst_n_combined -async -type reset -value low $_trst_obj
        set_rdc_define_assertion_sequence -from_reset [cdc_rst pwr_on_rst_ni] -to_reset {trst_n_combined}
        puts "INFO: dtp.resets: trst_n_combined declared as an independent reset under prefix '$::cdc_hier_prefix' (ordered after [cdc_rst pwr_on_rst_ni])"
    } else {
        puts "WARNING: dtp.resets: no net matches '[cdc_inst {u_jtag_intf_unit/u_jtag_ptap/u_trst_n_and/out_o[0]}]' - reset 'trst_n_combined' skipped"
    }
    unset _trst_obj
}

# JTAG TLR soft reset: synchronous active-high reset within the TCK domain.
_dtp_gen_reset tlr_reset high trst_n_combined {u_jtag_intf_unit/u_jtag_ptap/u_jtag_tap_ctrlr/u_test_logic_reset_flop/q_o[0]}

# Per-STAP gated resets: each is prim_and2(trst_n_combined, local rst_n). Guarded per
# entry: which STAPs exist depends on the DTP elaboration parameters.
foreach {rst_name rst_net} {
    stap_sep_dbg_rst  {u_jtag_intf_unit/gen_stap_sep_dbg.u_stap_sep_dbg/u_rst_n_and/out_o[0]}
    stap_io_rst       {u_jtag_intf_unit/gen_stap_io.u_stap_io/u_rst_n_and/out_o[0]}
    stap_3dcr_rst     {u_jtag_intf_unit/u_jtag_ptap/gen_tap_3dcr_reg.u_jtag_3dcr_reg/u_rst_n_and/out_o[0]}
    stap_extra0_rst   {u_jtag_intf_unit/gen_extra_staps.gen_extra_stap[0].u_stap_extra/u_rst_n_and/out_o[0]}
    stap_smc_dbg_rst  {u_jtag_intf_unit/gen_stap_smc_dbg.u_stap_smc_dbg/u_rst_n_and/out_o[0]}
} {
    _dtp_gen_reset $rst_name low trst_n_combined $rst_net
}

_dtp_gen_reset ic_reset_ctrl_rst_n low trst_n_combined {u_jtag_intf_unit/u_jtag_ptap/gen_ic_reset_reg.u_jtag_ic_reset_reg/reset_enable_control_scan_ctrl.rst_n}

rename _dtp_gen_reset {}
