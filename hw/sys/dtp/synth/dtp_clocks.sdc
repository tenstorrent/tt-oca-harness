# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# DTP clock stampings and TCK passthroughs.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Reads $clock_periods(...); the sourcing flow
# populates that array first.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "dtp_clocks.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

# Boundary clocks: block-top only. At a parent these nets carry the parent's clocks.
if {[cdc_is_block_top]} {
# System clock
create_clock -add -name DTPCLK -period $clock_periods(SYSCLK_PERIOD) [get_ports "clk_i"]

# JTAG TCK (from tap_ctrl struct)
create_clock -add -name JTAG_TCK -period $clock_periods(JTAG_TCK_PERIOD) [get_ports "jtag_ptap_client_tap_ctrl_i*tck"]

# feedthrough clock for any async input/outputs
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)
}


########################################################
# TCK clock passthroughs
########################################################
# TCK is routed combinationally from the PTAP client port to each downstream
# JTAG host. create_generated_clock tells the tool these are clock signals so
# it does not time them as data paths from the JTAG_TCK source.

create_generated_clock -name JTAG_TCK_BSR_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_bsr_host_scan_ctrl_o*tck"]

create_generated_clock -name JTAG_TCK_STAP_IO_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_stap_io_host_tap_ctrl_o*tck"]

create_generated_clock -name JTAG_TCK_STAP_SEP_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_stap_sep_host_tap_ctrl_o*tck"]

create_generated_clock -name JTAG_TCK_STAP_SMC_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_stap_smc_host_tap_ctrl_o*tck"]

set jtag_extra_stap_tck_ports [lsort -dictionary [get_object_name [get_ports {jtag_stap_extra_host_tap_ctrl_o*tck}]]]
set jtag_extra_stap_tck_idx 0
foreach jtag_extra_stap_tck_port $jtag_extra_stap_tck_ports {
    create_generated_clock [get_ports $jtag_extra_stap_tck_port] \
        -name JTAG_TCK_STAP_EXTRA_OUT${jtag_extra_stap_tck_idx} \
        -master_clock JTAG_TCK \
        -divide_by 1 \
        -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
        -combinational
    incr jtag_extra_stap_tck_idx
}

create_generated_clock -name JTAG_TCK_STAP_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_stap_host_scan_ctrl_o*tck"]

create_generated_clock -name JTAG_TCK_DFD_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_dfd_host_scan_ctrl_o*tck"]

create_generated_clock -name JTAG_TCK_DFT_SECURE_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_dft_secure_host_scan_ctrl_o*tck"]

create_generated_clock -name JTAG_TCK_DFT_OUT \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck"] \
    -combinational \
    [get_ports "jtag_dft_host_scan_ctrl_o*tck"]


