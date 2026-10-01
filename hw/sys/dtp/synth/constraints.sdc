# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# DTP (Debug and Test Ports) block-level timing constraints.
#
# Clock periods, generated clocks, and I/O delays for the `dtp` top-level
# port list (hw/sys/dtp/rtl/dtp.sv).
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2/abc.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Caveats, called out explicitly:
#   - `dtp` exposes three typed per-slice IC-reset ports,
#     `jtag_ic_reset_smc_o`, `jtag_ic_reset_sep_o`, and `jtag_ic_reset_ext_o`
#     (each with `.ovrd`/`.val` sub-structs); the constraints below cover all
#     three.
#   - `cla_clock_stop_en_o` and the DFT ports `test_en_i`/`scan_rst_ni` are
#     real `dtp` top-level ports; constraints below are modeled on their
#     nearest siblings (`stop_clks_o` and the SMC block's JTAG_TCK-domain DFT
#     ports, respectively).
#   - CDC crossings are bounded in two layers, both included from this file.
#     `set_async_clock_groups` below declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `dtp_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
#   - `dtp_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
#     It is produced once, offline, against an elaborated design and checked
#     in; nothing discovers instances when this file is read. Its paths and
#     clock names are OCAH's, so instantiating this block deeper in a
#     hierarchy or driving it from differently named clocks needs no edit
#     here -- set `::cdc_hier_prefix` and `::cdc_clock_alias` before sourcing
#     it. Regeneration, which runs in the closed synthesis flow, is needed
#     only when the block is reconfigured such that the set of CDC elements
#     changes: the file then goes stale silently, since no prefix can supply
#     constraints for elements it never listed.
#     See "CDC Timing Constraints" in the Integrator Guide.
#-----------------------------------------------------------------------------

# Directory holding this file, so the CDC collateral below resolves regardless
# of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/dtp/synth]
} else {
    error "constraints.sdc: cannot locate this file's directory; set GIT_ROOT"
}
set ocah_flow_constraints_dir [file normalize $ocah_sdc_dir/../../../../flows/synth/constraints]

##################
# CLOCK PERIODS
##################

# Units are picoseconds.
global clock_periods
set clock_periods(REFCLK_PERIOD)            10000
set clock_periods(SYSCLK_PERIOD)            1000
set clock_periods(PERIPHERALCLK_PERIOD)     5000
set clock_periods(SPICLK_PERIOD)            5000
set clock_periods(TELEMETRYCLK_PERIOD)      2000
set clock_periods(JTAG_TCK_PERIOD)          10000
set clock_periods(ck_feedthru_PERIOD)       10000
set clock_periods(WDTCLK_PERIOD)            10000
# Entropy periods below are non-functional; entropy_source is currently blackboxed.
set clock_periods(ENTROPY_ROSC_PERIOD)      2500
set clock_periods(ENTROPY_SHARED_RO_PERIOD) 2300

##################
# CLOCK STAMPINGS
##################

# System clock
create_clock -add -name DTPCLK -period $clock_periods(SYSCLK_PERIOD) [get_ports "clk_i"]

# JTAG TCK (from tap_ctrl struct)
create_clock -add -name JTAG_TCK -period $clock_periods(JTAG_TCK_PERIOD) [get_ports "jtag_ptap_client_tap_ctrl_i*tck"]

# feedthrough clock for any async input/outputs
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)


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


########################################################
# Async clock groups
########################################################
# Declared with `-allow_paths` plus a loose default bound on every inter-group
# clock pair. The per-instance bounds sourced at the end of this file refine
# that default; without `-allow_paths` they would be masked.
#
# This has to come after the TCK passthroughs above: the `JTAG_TCK_*` glob is
# resolved when the call runs, so a generated clock created later would be left
# out of the group and end up timed against DTPCLK as an unrelated domain.
source [file join $ocah_flow_constraints_dir async_clock_groups.tcl]

set_async_clock_groups {
    {DTPCLK DTPCLK_*}
    {JTAG_TCK JTAG_TCK_*}
    {ck_feedthru}
}


########################################################
# Input and Output delays
########################################################

# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports rst_n_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports pwr_on_rst_ni] -add_delay

# feature control (OTP/fuse bits) -- quasi-static
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.25]      -clock [get_clock DTPCLK] [get_ports {feat_ctrl_i*}] -add_delay

# JTAG interfaces
# Each input delay follows the TCK edge that launches the signal and each output
# delay precedes the rising edge that captures it. TDI, TMS, TRST and a
# downstream TAP's TDO change on the falling edge (-clock_fall); host scan-chain
# returns change on the rising edge. `.tck` fields carry generated clocks and
# take no data delay.
set jtag_io_ext [expr $clock_periods(JTAG_TCK_PERIOD)*0.2]

# JTAG PTAP client interface
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [filter_collection [get_ports {jtag_ptap_client_tap_ctrl_i*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_ptap_client_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_oen_o] -add_delay

# Boundary scan host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_bsr_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_out_o] -add_delay

# I/O STAP host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_io_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_stap_io_host_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_oen_o] -add_delay

# SEP Debug STAP host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_sep_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_stap_sep_host_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_sep_host_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_sep_host_tdo_oen_o] -add_delay

# SMC Debug STAP host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_smc_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_stap_smc_host_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_smc_host_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_smc_host_tdo_oen_o] -add_delay

# Extra STAP host interfaces (arrays)
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_extra_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports {jtag_stap_extra_host_tdi_i*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_oen_o*}] -add_delay

# Extended JTAG STAP scan host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_out_o] -add_delay

# External DFD iJTAG host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dfd_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_out_o] -add_delay

# External secure DFT iJTAG host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dft_secure_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_out_o] -add_delay

# External DFT iJTAG host interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dft_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_out_o] -add_delay

# SMC fabric debug AXI manager interface (system clock domain)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axi_smc_dbg_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axi_smc_dbg_resp_i*}] -add_delay

# SMC OTP debug AXI-Lite manager interface (system clock domain)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axil_smc_otp_jtag_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axil_smc_otp_jtag_resp_i*}] -add_delay

# SEP OTP debug AXI-Lite manager interface (system clock domain)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axil_sep_otp_jtag_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axil_sep_otp_jtag_resp_i*}] -add_delay

# Clock control
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports stop_clks_o] -add_delay
# `cla_clock_stop_en_o` is a real `dtp` top-level output; constrained the
# same as its `stop_clks_o` sibling.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports cla_clock_stop_en_o] -add_delay

# JTAG boot stall control (driven from JTAG_TCK-domain scan register; use TCK output delay)
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_boot_stall_ovrd_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_boot_stall_o] -add_delay

# JTAG reset control (typed struct slices; each contains `.ovrd` + `.val` halves).
# One typed port per IC_RESET TDR slice, driven from JTAG_TCK-domain flops.
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ic_reset_smc_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ic_reset_sep_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ic_reset_ext_o*}] -add_delay

# JTAG internal state (driven from JTAG_TCK-domain flops; use TCK output delay)
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_state_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_inst_decoded_o*}] -add_delay

# Cross trigger CSR AXI-Lite subordinate interface (system clock domain)
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axil_xtrig_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {axil_xtrig_resp_o*}] -add_delay

# Cross trigger matrix interface (async - uses feedthrough clock)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {xtrig_ctm_src_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_src_ack_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_dst_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {xtrig_ctm_dst_ack_o*}] -add_delay

# CLA clock stop interface
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_clk_stop_req_i*}] -add_delay

# Cross trigger port interface - GPIO pad ring (async - feedthrough clock)
# CT_Req_out
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_din_en_o*}] -add_delay

# CT_Req_in
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_din_en_o*}] -add_delay

# CT_Ack_in
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_din_en_o*}] -add_delay

# CT_Ack_out
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_din_en_o*}] -add_delay

# DFT
# `test_en_i`/`scan_rst_ni` are real `dtp` top-level ports; constrained on
# JTAG_TCK, matching the pattern used for the equivalent DFT ports on the
# SMC block.
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay
########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir dtp_cdc_max_delay.tcl]
