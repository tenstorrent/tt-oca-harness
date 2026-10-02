# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# sep.cdc_rdc_setup.tcl - SEP-specific CDC/RDC instance constraints
#
# Companion to flows/cdc/cdc_rdc_setup.tcl (shared type-level setup, sourced
# first): instance-level annotation for SEP-specific structures.
################################################################################

puts "INFO: Loading SEP-specific CDC/RDC constraints"

# Entropy source black-box boundary is SEPCLK-synchronous; tie its pins to a sync virtual clock
configure_unconstrained_ports -module entropy_source -input_model virtual_sync_all -output_model virtual_sync_all -use_inferred_domains

# VeeR PIC external-interrupt gateways: every external interrupt source is synchronised
# alone in its own pic_ctrl gateway (IO_CLK_GRP[*].GW[*].gw_inst/sync_inst, rvsyncss
# second stage sync_ff2) and the gateways' outputs are ORed / prioritised by the PIC and
# observed through the LSU address decode with no cross-bit coherency requirement
# (independent single-bit interrupts; same rationale as the signed-off tlu RECONV_COMB
# waivers SEP_CDC_COHERENCY_RECONV_COMB_5939/5940). Contribute the second-stage sync
# outputs to the convergence-ignore union instead of waiving the reconvergence. Generate labels carry
# brackets, so the cells are collected by full_name and each cell's Q pins taken literally.
if { [info procs cdc_conv_ignore_among] eq "" } {
    source $::env(GIT_ROOT)/flows/cdc/vc_procs.tcl
}
set _sep_pic_sync_cells [get_cells -hier -filter {full_name =~ *pic_ctrl_inst/IO_CLK_GRP*gw_inst/sync_inst/sync_ff2/*dout} -quiet]
set _sep_pic_sync_pins [list]
foreach_in_collection c $_sep_pic_sync_cells {
    set p [get_pins -quiet "[get_object_name $c]/Q*"]
    if {[sizeof_collection $p] > 0} { lappend _sep_pic_sync_pins {*}[get_object_name $p] }
}
if { [llength $_sep_pic_sync_pins] > 0 } {
    cdc_conv_ignore_among $_sep_pic_sync_pins
    puts "INFO: conv-ignore-among: SEP PIC gateway syncs => [llength $_sep_pic_sync_pins] pins"
} else {
    puts "WARNING: conv-ignore-among: no pic_ctrl_inst gateway sync_ff2 cells found - skipped"
}
unset -nocomplain _sep_pic_sync_cells _sep_pic_sync_pins

puts "INFO: SEP-specific CDC/RDC constraints loaded."
