# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMU input and output delays.
#
# Shared with the closed block flow. Source smu_clocks.sdc first: every delay
# references a clock it stamps.
#-----------------------------------------------------------------------------

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

if {![array exists ::clock_periods]} {
    error "smu_io_delays.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

if {![info exists smu_owns_child_copies]} {
    error "smu_io_delays.sdc: source smu_clocks.sdc before this file"
}

########################################################
# Input and Output delays
########################################################

# resets
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports powergood_i] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cold_ni] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_cold_stable_ref_clk_no] -add_delay

set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_primary_ref_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports rst_primary_smc_clk_no] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cool_n_from_pin_i] -add_delay

# AXI / AXI-Lite interfaces
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_in_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_out_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_out_resp_i*}] -add_delay


set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_external_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_shim_command_resp_i*}] -add_delay

# SMC / SEP apertures, surfaced symmetrically at the SMU boundary.
# `smc_global_base_o*` is constrained the same as its sibling
# `smc_region_size_o*`.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_global_base_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_region_size_o*}] -add_delay
# Addition: `sep_global_base_o*` / `sep_region_size_o*` mirror the SMC apertures
# above; tied to '0 when CFG.SEP=0 but still SMUCLK-domain CSR outputs when CFG.SEP=1.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_global_base_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_region_size_o*}] -add_delay

# GPIO Data Signals
# Full hierarchy (synth): the GPIO Interface section below carries the
# protocol-accurate per-bit delays.
# SAM flow (CDC/RDC): the protocol clocks that section needs live inside the
# SMC SAM and are not defined at the SMU boundary, so the pads are async
# feedthroughs into the SAM and take the boundary clock instead. Without this
# they are unconstrained.
if {$smu_sam_flow} {
    set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {pad2core_i*}]              -add_delay
    set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {core2pad_o*}]              -add_delay
    set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {core2pad_en_o*}]           -add_delay
    set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {pad2core_en_o*}]           -add_delay
    set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] [get_ports {lsio_interface_select_o*}] -add_delay
}

# telemetry
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports rst_telemetry_ni] -add_delay

set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atdata_i*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atready_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atvalid_i*}] -add_delay
# afvalid_o leaves telemetry_receiver_wrap through a synchronizer clocked by
# clk_telemetry_i, so the whole ATB interface is TELEMETRYCLK. Stamped once, here
# only, to keep the port single-clocked.
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afvalid_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afready_i*}] -add_delay

# WDT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_wdt_first_timeout_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_wdt_second_timeout_o] -add_delay

# interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ext_interrupts_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_ext_mailbox_interrupts_o*}] -add_delay
# `gpio_interrupt_o*` / `uart_interrupt_o*` are real `smu` top-level
# interrupt outputs, modeled the same as the other SMUCLK-domain interrupt
# outputs above.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {gpio_interrupt_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {uart_interrupt_o*}] -add_delay

# efuse
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_shadow_regs_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_fuse_sense_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_fuse_reset_n_delayed_o] -add_delay

# DFT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports skip_mem_repair_o] -add_delay

# LC
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {lc_state_o*}] -add_delay

# RAS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_cluster_ded_o] -add_delay

# NDM
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ndmreset_request_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_ndmreset_process_o*}] -add_delay

# reset unit
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cfg_flr_pf_active_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {isolate_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ss_reset_complete_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ss_config_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ss_reset_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports sync_irq_o] -add_delay

# will transition once to indicate status of POR DFX logic
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_boot_seq_done_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mem_repair_done_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mem_repair_success_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mem_repair_abort_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mbist_done_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mbist_pass_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mbist_abort_i}] -add_delay

# will transition once as a strap (one time capture on cold reset de-assertion)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_disable_sram_auto_init_i}] -add_delay

# memory
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_rom_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {smc_rom_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_scratch_ram_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_scratch_ram_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_icache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_icache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_icache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_icache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_dcache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_dcache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_dcache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_dcache_data_intf_rsp_i*}] -add_delay

# Trace Memory
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {trace_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {trace_mem_resp_i*}] -add_delay

# OCTS
# Quasi-static: a chiplet identity strap, settled before the timer comes out of
# reset and constant thereafter, so no arrival window needs reserving. Zero
# keeps the port timed rather than exempted.
set_input_delay 0 -clock [get_clock ck_feedthru] [get_ports chiplet_is_primary_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {timer_count_o*}] -add_delay

# External Debug Bus
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_debug_bus_i*}] -add_delay

# Test
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports test_en_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports scan_rst_ni] -add_delay

# Memory Init
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_init_mem_done_o] -add_delay

# I3C DAT/DCT memory interfaces (see the same construct in the SMC block
# SDC). I/O delays are stamped on PERIPHERALCLK for both directions - the
# `_src_i` inputs and the `_sink_o` responses (real `smu` top-level outputs)
# - guarded with `-quiet` since I3C is a configurable peripheral count.
set i3c_dmem_src_ports [get_ports -quiet "i3c_dat_mem_src_i*"]
if {[sizeof_collection $i3c_dmem_src_ports] > 0} {
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dmem_src_ports -add_delay
}
set i3c_dmem_sink_ports [get_ports -quiet "i3c_dat_mem_sink_o*"]
if {[sizeof_collection $i3c_dmem_sink_ports] > 0} {
    set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dmem_sink_ports -add_delay
}
set i3c_dctmem_src_ports [get_ports -quiet "i3c_dct_mem_src_i*"]
if {[sizeof_collection $i3c_dctmem_src_ports] > 0} {
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dctmem_src_ports -add_delay
}
set i3c_dctmem_sink_ports [get_ports -quiet "i3c_dct_mem_sink_o*"]
if {[sizeof_collection $i3c_dctmem_sink_ports] > 0} {
    set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dctmem_sink_ports -add_delay
}


########################################################
# JTAG Interface Constraints (SMU-specific)
########################################################

# Each input delay follows the TCK edge that launches the signal and each output
# delay precedes the rising edge that captures it. TDI, TMS, TRST and a
# downstream TAP's TDO change on the falling edge (-clock_fall); host scan-chain
# returns change on the rising edge. `.tck` fields carry generated clocks and
# take no data delay. The budget matches the DTP block constraints.
set jtag_io_ext [expr $clock_periods(JTAG_TCK_PERIOD)*0.2]

# Primary JTAG TAP Interface
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [filter_collection [get_ports {jtag_ptap_client_tap_ctrl_i*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_ptap_client_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_oen_o] -add_delay

# Boundary Scan Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_bsr_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_out_o] -add_delay

# I/O STAP Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_io_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_stap_io_host_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_oen_o] -add_delay

# Extra STAP Interfaces
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_extra_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports {jtag_stap_extra_host_tdi_i*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_oen_o*}] -add_delay

# Extended STAP Scan Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_out_o] -add_delay

# DFD iJTAG Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dfd_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_out_o] -add_delay

# Secure DFT iJTAG Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dft_secure_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_out_o] -add_delay

# DFT iJTAG Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dft_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_out_o] -add_delay

# JTAG State Outputs
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_state_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_inst_decoded_o*}] -add_delay

# `jtag_ic_reset_ext_o` is a real `smu` top-level output (the external slice
# of DTP's IC_RESET TDR), modeled the same as the other JTAG_TCK-domain state
# outputs above. Width follows `ic_reset_ext_t`; the integrator carries the SEP
# xSPI reset overrides here, so the wildcard must stay a wildcard.
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ic_reset_ext_o*}] -add_delay

# DTP Clock Stop Output
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports dtp_stop_clks_o] -add_delay


########################################################
# Cross Trigger Matrix Constraints (SMU-specific)
########################################################

# Cross Trigger Matrix Interface (external ports [7:0] exposed)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctm_src_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_src_ack_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_dst_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctm_dst_ack_o*}] -add_delay

# Clock Stop Request Interface (external ports [7:0] exposed)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_clk_stop_req_i*}] -add_delay


########################################################
# Cross Trigger Port GPIO Constraints (SMU-specific)
########################################################

# Cross Trigger Port GPIO Interface (16 CTPs)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_out_din_en_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_in_din_en_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_in_din_en_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_out_din_en_o*}] -add_delay


########################################################
# SEP Passthrough Ports (to/from sep_ip_integration in smu_wrapper)
########################################################

# SEP Memory Interfaces
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_boot_rom_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {sep_boot_rom_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_cpu_tcm_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {sep_cpu_tcm_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_imem_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_imem_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_dmem_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_dmem_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_km_rom_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {sep_km_rom_mem_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_km_sram_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_km_sram_mem_rsp_i*}] -add_delay

# SEP eFuse Interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_bank_ctrl_resp_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_shim_command_resp_i*}] -add_delay

# SEP Crypto Interfaces
# `sep_crypto_entropy_req_o*` / `sep_crypto_entropy_rsp_i*` do not exist at
# the current `smu` top level -- see the file header. Left commented out for
# traceability.
# set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_entropy_req_o*}] -add_delay
# set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_entropy_rsp_i*}] -add_delay

# SEP External
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_external_resp_i*}] -add_delay

# SEP Reset

# SEP CPU Trace
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_cpu_trace_o*}] -add_delay

# SEP External Interrupts. `sep_ext_interrupts_i` is a real `smu` top-level
# input feeding `u_sep` directly; modeled the same as the other
# ck_feedthru-domain inputs above.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {sep_ext_interrupts_i*}] -add_delay

# SEP Adams-Bridge crypto memory interface, 1:1 passthroughs of the `u_sep`
# ports; SEP stamps them on SEPCLK, which is SMUCLK here.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {abr_mem_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {abr_mem_rsp_i*}] -add_delay

# External TRNG interface, likewise SEPCLK at the SEP boundary.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ext_trng_axil_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ext_trng_axil_resp_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ext_trng_axis_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ext_trng_axis_rsp_o*}] -add_delay
# An asynchronous interrupt, resynchronized inside the block, so almost none
# of the period is owed to its arrival.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.1]  -clock [get_clock ck_feedthru] [get_ports ext_trng_irq_i] -add_delay

# LCC Demote States
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {lcc_demote_state_1_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {lcc_demote_state_2_o*}] -add_delay

# SEP Fuse Sense Done
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports sep_fuse_sense_done_o] -add_delay

# SEP Straps
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {secure_tm_req_i}] -add_delay

# SEP Security Disable
# `sep_security_disable_i` does not exist at the current `smu` top level --
# see the file header (the signal is a purely internal net between u_sep and
# u_smc). Left commented out for traceability.
# set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports sep_security_disable_i] -add_delay

########################################################
# GPIO Interface
########################################################
# The padring is SMC's, passed through unchanged, so the bit assignments and
# external budgets come from SMC's own file rather than a second copy here.
# SMU's system clock takes the place of SMCCLK, and SPI stays untimed: SMU
# exposes neither spi_clk_i nor the spi_rxd_o / spi_rxds_o read ports the SPI
# sections reference, so those pads fall through to the generic ck_feedthru
# model that file applies.
if {$smu_owns_child_copies} {
    set gpio_sys_clk SMUCLK
    source [file normalize [file join [file dirname [info script]] \
        ../../smc/synth/smc_gpio_io_delays.sdc]]
}
