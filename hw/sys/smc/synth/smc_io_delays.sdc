# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC top-level input and output delays, excluding the GPIO/padring boundary.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. The GPIO/padring boundary is in
# smc_gpio_io_delays.sdc.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "smc_io_delays.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

if {![array exists ::io_budget]} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/io_delay_budgets.tcl]]
}

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

# Block-top only: these delays anchor the block's own ports. Replayed under a parent
# they are internal nets whose launch and capture domains come from the real fabric.
if {[cdc_is_block_top]} {

# resets
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports powergood_i] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*$io_budget(default)]       -clock [get_clock REFCLK] [get_ports powergood_stable_o] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports rst_cold_ni] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*$io_budget(default)]       -clock [get_clock REFCLK] [get_ports rst_cold_stable_ref_clk_no] -add_delay

set_output_delay [expr $clock_periods(REFCLK_PERIOD)*$io_budget(default)]       -clock [get_clock REFCLK] [get_ports rst_primary_ref_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports rst_primary_smc_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports rst_wdt_smc_clk_no] -add_delay
# `rst_primary_periph_clk_no` is a real `smc` top-level output; constrained
# on PERIPHERALCLK to match its name, following the same 50%-period margin
# pattern as its sibling reset outputs.
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*$io_budget(default)] -clock [get_clock PERIPHERALCLK] [get_ports rst_primary_periph_clk_no] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports rst_cool_n_from_pin_i] -add_delay

# AXI / AXI-Lite interfaces
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {sys_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {sys_axi_in_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {jtag_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {jtag_axi_in_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {axil_smc_otp_jtag_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {axil_smc_otp_jtag_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {sep_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {sep_axi_in_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {output_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {output_axi_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {axil_dtp_csr_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {axil_dtp_csr_resp_i*}] -add_delay

# The GPIO padring, PLL, PVT and eFuse SHIM control planes all reach the adopter
# through smc_external below; they are SMC-domain by contract. Adopter-specific
# refclk logic behind that window must add any local CDC explicitly rather than
# reinterpret these top-level ports as REFCLK ports.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {smc_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {smc_external_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {efuse_shim_command_resp_i*}] -add_delay

# telemetry
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports rst_telemetry_ni] -add_delay

set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atdata_i*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atready_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atvalid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afvalid_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*$io_budget(default)] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afready_i*}] -add_delay

# WDT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports smc_wdt_first_timeout_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports smc_wdt_second_timeout_o] -add_delay

# interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {smc_ext_interrupts_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {sep_mailbox_interrupts_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports sep_wdt_reset_n_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {smc_ext_mailbox_interrupts_o*}] -add_delay

# efuse
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {shadow_regs_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports smc_fuse_sense_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports smc_fuse_reset_n_delayed_o] -add_delay

# boot stall
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports boot_stall_jtag_ovrd_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports boot_stall_jtag_val_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports boot_stall_combined_o] -add_delay

# DFT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports skip_mem_repair_o] -add_delay
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# LC
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {lc_state_i*}] -add_delay

# RAS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports smc_cluster_ded_o] -add_delay

# NDM
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {smc_ndmreset_request_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {smc_ndmreset_process_o*}] -add_delay

# reset unit
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports cfg_flr_pf_active_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {isolate_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports {ss_reset_complete_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {ss_config_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {ss_reset_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports sync_irq_o] -add_delay

# memory
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_rom_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(rom_rsp)]       -clock [get_clock SMCCLK] [get_ports {smc_rom_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_scratch_ram_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(sram_rsp)]       -clock [get_clock SMCCLK] [get_ports {smc_scratch_ram_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_icache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(sram_rsp)]       -clock [get_clock SMCCLK] [get_ports {smc_l1_icache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_icache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(sram_rsp)]       -clock [get_clock SMCCLK] [get_ports {smc_l1_icache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_dcache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(sram_rsp)]       -clock [get_clock SMCCLK] [get_ports {smc_l1_dcache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_dcache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(sram_rsp)]       -clock [get_clock SMCCLK] [get_ports {smc_l1_dcache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(mem_req)]       -clock [get_clock SMCCLK] [get_ports {trace_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(sram_rsp)]       -clock [get_clock SMCCLK] [get_ports {trace_mem_resp_i*}] -add_delay

# OCTS
# Quasi-static: a chiplet identity strap, settled before the timer comes out of
# reset and constant thereafter, so no arrival window needs reserving. Zero
# keeps the port timed rather than exempted.
set_input_delay 0 -clock [get_clock ck_feedthru] [get_ports chiplet_is_primary_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {timer_count_o*}] -add_delay

# DFD
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports xtrigger_ss_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports xtrigger_ss_o] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports ext_debug_bus_i] -add_delay

# Test
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay


# DFT
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports mem_repair_done_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports mem_repair_success_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports mem_repair_abort_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports mbist_done_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports mbist_pass_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports mbist_abort_i] -add_delay

# SPI signals below are more relaxed than the typical 50% delay because they just pass through SMC

# SPI enable (controlled by internal registers)
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.4]       -clock [get_clock SMCCLK] [get_ports spi_enable_i] -add_delay

# SPI data and pad control signals
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_clk_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_clk_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_dqs_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_dqs_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_dq_ie_n_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_dq_oe_n_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_oepad_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_iepad_i] -add_delay

# The data ports are one end of the pad feedthroughs, whose hop the SPI pad
# window bounds. The commercial synthesis tool charges any I/O delay here
# against that window, so they carry zero; the zero only keeps them on SPICLK.
set_input_delay  0 -clock [get_clock SPICLK] [get_ports {spi_txd_i*}] -add_delay
set_input_delay  0 -clock [get_clock SPICLK] [get_ports spi_cs_n_i] -add_delay
set_input_delay  0 -clock [get_clock SPICLK] [get_ports spi_mem_rebar_opad_i] -add_delay
set_output_delay 0 -clock [get_clock SPICLK] [get_ports {spi_rxd_o*}] -add_delay
set_output_delay 0 -clock [get_clock SPICLK] [get_ports spi_rxds_o] -add_delay
set_output_delay 0 -clock [get_clock SPICLK] [get_ports spi_mem_rebar_ipad_o] -add_delay

# I3C DAT/DCT/RLT memory interfaces (struct-flattened port names). Tied or driven
# from the memory controller in chip context; stamp PERIPHERALCLK for block CDC SETUP.
# Guarded with -quiet since I3C is a configurable peripheral count.
foreach mem {dat dct rlt} {
    set i3c_mem_src_ports [get_ports -quiet "i3c_${mem}_mem_src_i*"]
    if {[sizeof_collection $i3c_mem_src_ports] > 0} {
        set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*$io_budget(default)] -clock [get_clock PERIPHERALCLK] $i3c_mem_src_ports -add_delay
        puts "INFO: set_input_delay PERIPHERALCLK on i3c_${mem}_mem_src_i* ([sizeof_collection $i3c_mem_src_ports] ports)"
    }
    set i3c_mem_sink_ports [get_ports -quiet "i3c_${mem}_mem_sink_o*"]
    if {[sizeof_collection $i3c_mem_sink_ports] > 0} {
        set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*$io_budget(default)] -clock [get_clock PERIPHERALCLK] $i3c_mem_sink_ports -add_delay
        puts "INFO: set_output_delay PERIPHERALCLK on i3c_${mem}_mem_sink_o* ([sizeof_collection $i3c_mem_sink_ports] ports)"
    }
}

# SMC control/status signals
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {smc_global_base_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {smc_region_size_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports smc_init_mem_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports {cla_ext_action_custom_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*$io_budget(default)]       -clock [get_clock SMCCLK] [get_ports tdr_dbg_ctrl_clocks_stopped_by_cla_o] -add_delay

# Quasi-static: the SEP eFuse drives this once the fuses are sensed and it
# holds for the rest of the power cycle, so no part of the period has to be
# reserved for its arrival. Zero keeps the port timed rather than exempted.
set_input_delay 0 -clock [get_clock SMCCLK] [get_ports sep_security_disable_i] -add_delay

# For us its driven by captured straps | shadow reg, but for an adopter its hard to say. Should not assume anything about the source of this signal.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*$io_budget(default)]  -clock [get_clock ck_feedthru] [get_ports smc_disable_sram_auto_init_i] -add_delay
# `tdr_dbg_ctrl_clock_stop_en_i` is driven by the DTP DEBUG_CONTROL TDR (JTAG_TCK);
# the functional scenario pins it by case analysis, so the delay applies elsewhere.
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports tdr_dbg_ctrl_clock_stop_en_i] -add_delay

# CPU debug JTAG -- same budget as the DTP block constraints. The host launches
# TMS/TDI/reset on the falling TCK edge (-clock_fall) and samples TDO on the rising edge.
set jtag_io_ext [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(jtag)]
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports {smc_cpu_jtag_TMS_i}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports {smc_cpu_jtag_TDI_i}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TDO_data_o}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports {smc_cpu_jtag_reset_i}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_mfr_id_i*}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_part_number_i*}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_version_i*}] -add_delay

cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports {jtag_reset_ctrl_i.val*}] -add_delay
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*$io_budget(default)]     -clock [get_clock JTAG_TCK] [get_ports {jtag_reset_ctrl_i.ovrd*}] -add_delay

}
# end of block-top-only smc_io_delays
