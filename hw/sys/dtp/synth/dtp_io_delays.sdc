# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# DTP top-level input and output delays.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Reads $clock_periods(...); the sourcing flow
# populates that array first.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "dtp_io_delays.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

if {![array exists ::io_budget]} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/io_delay_budgets.tcl]]
}

# Block-top only: these delays anchor the block's own ports. Replayed under a parent
# they are internal nets whose launch and capture domains come from the real fabric.
if {[cdc_is_block_top]} {

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}


# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports rst_n_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports pwr_on_rst_ni] -add_delay

# feature control (OTP/fuse bits) -- quasi-static
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.25]      -clock [get_clock DTPCLK] [get_ports {dbg_disable_i*}] -add_delay

# JTAG interfaces
# Each input delay follows the TCK edge that launches the signal and each output
# delay precedes the rising edge that captures it. TDI, TMS, TRST and a
# downstream TAP's TDO change on the falling edge (-clock_fall); host scan-chain
# returns change on the rising edge. `.tck` fields carry generated clocks and
# take no data delay.
set jtag_io_ext [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(jtag)]

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
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axi_smc_dbg_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axi_smc_dbg_resp_i*}] -add_delay

# SMC OTP debug AXI-Lite manager interface (system clock domain)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axil_smc_otp_jtag_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axil_smc_otp_jtag_resp_i*}] -add_delay

# SEP OTP debug AXI-Lite manager interface (system clock domain)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axil_sep_otp_jtag_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axil_sep_otp_jtag_resp_i*}] -add_delay

# Clock control
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports stop_clks_o] -add_delay
# `cla_clock_stop_en_o` is bit 2 of the DEBUG_CONTROL TDR update register, so it
# launches from JTAG_TCK like the boot-stall outputs below, not from DTPCLK.
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports cla_clock_stop_en_o] -add_delay

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
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axil_xtrig_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {axil_xtrig_resp_o*}] -add_delay

# Cross trigger matrix interface (async - uses feedthrough clock)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {xtrig_ctm_src_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_src_ack_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_dst_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock DTPCLK] [get_ports {xtrig_ctm_dst_ack_o*}] -add_delay

# CLA clock stop interface
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_clk_stop_req_i*}] -add_delay

# Cross trigger port interface - GPIO pad ring (async - feedthrough clock)
# CT_Req_out
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_din_en_o*}] -add_delay

# CT_Req_in
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_din_en_o*}] -add_delay

# CT_Ack_in
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_din_en_o*}] -add_delay

# CT_Ack_out
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_din_en_o*}] -add_delay

# DFT
# `test_en_i`/`scan_rst_ni` are real `dtp` top-level ports; constrained on
# JTAG_TCK, matching the pattern used for the equivalent DFT ports on the
# SMC block.
set_input_delay 0 -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
set_input_delay 0 -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay

}
# end of block-top-only input and output delays
