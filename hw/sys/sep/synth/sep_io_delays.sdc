# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP top-level input and output delays.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Reads $clock_periods(...); the sourcing flow
# populates that array first.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "sep_io_delays.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

# Block-top only: these delays anchor the block's own ports. Replayed under a parent
# they are internal nets whose launch and capture domains come from the real fabric.
if {[cdc_is_block_top]} {

# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports rst_ni] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dbg_rstb_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports wdt_rst_ni] -add_delay
set_output_delay [expr $clock_periods(WDTCLK_PERIOD)*0.5]       -clock [get_clock WDTCLK] [get_ports wdt_timer_rst_req_o] -add_delay

# JTAG -- 45% so the negedge TCK flops have a chance of meeting timing
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.45]     -clock [get_clock JTAG_TCK] [get_ports jtag_tms_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.45]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdi_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.45]  -clock [get_clock ck_feedthru] [get_ports jtag_trst_ni] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.45]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdo_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.45]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdoEn_o] -add_delay

# OTP debug AXI-Lite interface
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axil_sep_otp_jtag_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axil_sep_otp_jtag_resp_o*}] -add_delay

# MPC debug interface (async)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_debug_halt_req_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_debug_run_req_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_reset_run_req_i] -add_delay

# CPU halt/run interface (async)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cpu_halt_req_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cpu_run_req_i] -add_delay

# JTAG SEP reset control overrides (TCK domain)
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.val*}] -add_delay
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.ovrd*}] -add_delay

# Test
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay

# Boot sequence done
cdc_pinned_port_delay set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# DMI interface
# - only SEPCLK because there is no internal synchronization like the mpc or cpu_halt
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_core_enable_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_enable_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_en_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_wr_en_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_addr_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_wdata_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_rdata_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_active_o] -add_delay

# CPU trace
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_trace_o*}] -add_delay

# CPU configuration inputs
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {jtag_id_i*}] -add_delay

# Interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports timer_int_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports soft_int_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {extintsrc_req_i*}] -add_delay

# SEP memories
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [remove_from_collection [get_ports {sep_cpu_tcm_req_o*}] [get_ports {sep_cpu_tcm_req_o*clk}]] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_tcm_rsp_i*}] -add_delay

# Scratchpad SRAM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_sram_rsp_i*}] -add_delay

# Boot ROM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_rsp_i*}] -add_delay

# Key Manager memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_rsp_i*}] -add_delay

# Adams-Bridge crypto memory interface (request out to macros, response data back)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {abr_mem_req*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {abr_mem_rsp*}] -add_delay

# Crypto PKA memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_imem_sram_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_imem_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_dmem_sram_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_dmem_sram_rsp_i*}] -add_delay

# SMN AXI interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_outbound_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_outbound_axi_resp_i*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_inbound_axi_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_inbound_axi_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_ext_to_smc_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_ext_to_smc_axi_resp_i*}] -add_delay

# External TRNG interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axil_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axil_resp_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axis_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axis_rsp_o*}] -add_delay
# An asynchronous interrupt, resynchronized inside the block, so almost none
# of the period is owed to its arrival.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.1]  -clock [get_clock ck_feedthru] [get_ports ext_trng_irq_i] -add_delay

# Key Manager interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports km_unrecoverable_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports km_recoverable_err_o] -add_delay

# Efuse interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_shim_command_resp_i*}] -add_delay

# LC demote state
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lcc_demote_state_1_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lcc_demote_state_2_o*}] -add_delay

# IO interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_io_spi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_io_spi_rsp_i*}] -add_delay

# LC state
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lc_state_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports security_disable_o] -add_delay

# Mailbox interrupts
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smc_mailbox_interrupt_o*}] -add_delay

# Fuse sense status
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports smc_fuse_sense_done_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports sep_fuse_sense_done_o] -add_delay

# Straps
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {secure_tm_req_i}] -add_delay

# SEP external interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_external_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_external_axi_resp_i*}] -add_delay

# SMC address configuration
# - don't need much delay as it is just a register directly from SMC
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.2]       -clock [get_clock SEPCLK] [get_ports {smc_global_base_addr_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.2]       -clock [get_clock SEPCLK] [get_ports {smc_region_size_i*}] -add_delay

# SEP aperture configuration
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_global_base_addr_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_region_size_o*}] -add_delay

# External debug bus
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_debug_bus_o*}] -add_delay

}
# end of block-top-only input and output delays
