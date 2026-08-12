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
#   - CDC crossings are NOT bounded by this file. The flow bounds every
#     crossing in two layers: asynchronous clock groups declared with
#     `-allow_paths` plus a loose default max_delay per inter-group clock
#     pair, and a per-instance `set_max_delay` on each synchronizer and async
#     FIFO. Neither layer is reproduced here -- the per-instance layer is
#     generated against the block hierarchy and must be regenerated whenever
#     the RTL changes, so a copy in this file would go stale silently.
#     Note that `set_clock_groups -asynchronous` below is the bare form:
#     `set_false_path` outranks `set_max_delay` in exception priority, so if
#     this SDC ever becomes a real STA/P&R input, that line needs
#     `-allow_paths` or it will mask every per-instance bound.
#     The DTP async groups also need the JTAG_TCK passthrough clocks
#     (`JTAG_TCK_*`) grouped with JTAG_TCK; the flow does this, this file
#     does not. See "CDC Timing Constraints" in the Integrator Guide.
#-----------------------------------------------------------------------------

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

set_clock_groups -asynchronous \
    -group {DTPCLK}\
    -group {JTAG_TCK}\
    -group {ck_feedthru}


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
# Input and Output delays
########################################################

# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports rst_n_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports pwr_on_rst_ni] -add_delay

# feature control (OTP/fuse bits) -- quasi-static
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.25]      -clock [get_clock DTPCLK] [get_ports {feat_ctrl_i*}] -add_delay

# JTAG PTAP client interface
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.75]    -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_client_tap_ctrl_i*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.75]    -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdi_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_oen_o] -add_delay

# Boundary scan host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_bsr_host_scan_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_in_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_out_o] -add_delay

# I/O STAP host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_io_host_tap_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.75]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdi_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_oen_o] -add_delay

# SEP Debug STAP host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_sep_host_tap_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.75]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_sep_host_tdi_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_sep_host_tdo_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_sep_host_tdo_oen_o] -add_delay

# SMC Debug STAP host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_smc_host_tap_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.75]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_smc_host_tdi_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_smc_host_tdo_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_smc_host_tdo_oen_o] -add_delay

# Extra STAP host interfaces (arrays)
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tap_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.75]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdi_i*}] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_o*}] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_oen_o*}] -add_delay

# Extended JTAG STAP scan host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_host_scan_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_in_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_out_o] -add_delay

# External DFD iJTAG host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_dfd_host_scan_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_in_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_out_o] -add_delay

# External secure DFT iJTAG host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_dft_secure_host_scan_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_in_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_out_o] -add_delay

# External DFT iJTAG host interface
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_dft_host_scan_ctrl_o*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_in_i] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_out_o] -add_delay

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
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_boot_stall_ovrd_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports jtag_boot_stall_o] -add_delay

# JTAG reset control (typed struct slices; each contains `.ovrd` + `.val` halves).
# One typed port per IC_RESET TDR slice.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {jtag_ic_reset_smc_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {jtag_ic_reset_sep_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock DTPCLK] [get_ports {jtag_ic_reset_ext_o*}] -add_delay

# JTAG internal state (driven from JTAG_TCK-domain flops; use TCK output delay)
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_state_o*}] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.25]    -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_inst_decoded_o*}] -add_delay

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
