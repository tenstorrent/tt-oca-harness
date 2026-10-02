# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#-----------------------------------------------------------------------------
# DTP (Debug and Test Ports) block-level timing constraints.
#
# Clocks, generated clocks, and I/O delays for the `dtp` top-level port list
# (hw/sys/dtp/rtl/dtp.sv).
#
# Read by synthesis as the block SDC, by the CDC/RDC sign-off run through
# cdc/dtp.cdc_rdc.tcl, and by any parent that replays this block under a
# hierarchy prefix (hw/sys/smu). Clock periods come from
# flows/synth/constraints/clock_periods.tcl; the hooks from cdc_hier_procs.tcl.
#
# Hierarchy-reusable: boundary constraints (create_clock on ports, the generated
# TCK output-port clocks, IO delays, clock groups) apply at block top only. At
# the SMU top these nets carry SMU's clocks (DTPCLK -> SMUCLK via
# ::cdc_clock_alias); the TCK feedthrough pins are covered by JTAG_TCK
# propagation and SMU's own port stampings.
#
# Caveats, called out explicitly:
#   - `dtp` exposes three typed per-slice IC-reset ports,
#     `jtag_ic_reset_smc_o`, `jtag_ic_reset_sep_o`, and `jtag_ic_reset_ext_o`
#     (each with `.ovrd`/`.val` sub-structs); the constraints below cover all
#     three.
#   - The DFT ports `test_en_i`/`scan_rst_ni` take a JTAG_TCK input delay in
#     the synth scenario only; the functional scenario leaves them unpinned
#     and undelayed, since `dtp` carries no case analysis of its own.
#   - `cla_clock_stop_en_o` carries no output delay.
#   - CDC crossings are bounded in two layers. `cdc_apply_async_groups` below
#     declares the asynchronous groups; in the synth scenario it goes through
#     `set_async_clock_groups`, which adds `-allow_paths` and a loose default
#     max_delay per inter-group clock pair, and `dtp_cdc_max_delay.tcl`,
#     sourced at the end, tightens each synchronizer and async FIFO
#     individually. The `-allow_paths` is not optional: `set_false_path`
#     outranks `set_max_delay` in exception priority, so a bare
#     `set_clock_groups -asynchronous` would silently mask every per-instance
#     bound. The functional (sign-off) scenario emits the bare form and skips
#     the bounds.
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

# Directory holding this file, so the shared collateral below resolves regardless
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

# Clock periods and the hierarchy-reuse hooks every constraint below goes through.
source [file join $ocah_flow_constraints_dir clock_periods.tcl]
if {[info procs cdc_is_block_top] eq ""} {
    source [file join $ocah_flow_constraints_dir cdc_hier_procs.tcl]
}


##################
# CLOCK STAMPINGS
##################

if {[cdc_is_block_top]} {
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

}
# end of block-top-only clock stampings

# Async-domain membership: the generated TCK output clocks are feedthrough copies of
# JTAG_TCK and belong in its group. cdc_apply_async_groups emits the groups once and drops
# any name that does not exist in this configuration.
cdc_group_extra JTAG_TCK {JTAG_TCK_BSR_OUT JTAG_TCK_STAP_IO_OUT JTAG_TCK_STAP_SEP_OUT \
                          JTAG_TCK_STAP_SMC_OUT JTAG_TCK_STAP_EXTRA_OUT0 JTAG_TCK_STAP_OUT \
                          JTAG_TCK_DFD_OUT JTAG_TCK_DFT_SECURE_OUT JTAG_TCK_DFT_OUT}

if {[cdc_is_block_top]} {
    cdc_apply_async_groups {DTPCLK JTAG_TCK ck_feedthru}
}


########################################################
# Input and Output delays
########################################################
# Block-top only: IO delays anchor the block's own ports; at the parent these are internal
# nets whose launch/capture domains come from the real fabric.
if {[cdc_is_block_top]} {

# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports rst_n_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports pwr_on_rst_ni] -add_delay

# debug-disable straps (fuse/CSR sourced) -- quasi-static
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.25]      -clock [get_clock DTPCLK] [get_ports {dbg_disable_i*}] -add_delay

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

# DFT (pinned by case analysis in the functional scenario, so the delay applies only where they are not pinned)
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay

}
# end of block-top-only Input and Output delays

########################################################
# CDC max_delay bounds
########################################################
# Layer 2 of the synthesis CDC constraints: a per-instance bound on every
# synchronizer and async FIFO, tighter than the inter-group default that
# cdc_apply_async_groups applies in the bounded synth scenario. Loaded last so
# these exceptions are the ones the tool keeps where both apply, and so the
# primary-input relaxation at the end sees every constrained pin. Block top
# only, synth scenario only, and only while ::cdc_bound_crossings is set.
if {[cdc_is_block_top] && $::cdc_scenario eq "synth" && $::cdc_bound_crossings} {
    source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
    source [file join $ocah_sdc_dir dtp_cdc_max_delay.tcl]
}
