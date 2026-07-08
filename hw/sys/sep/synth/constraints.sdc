# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP (Secure Enclave Processor) block-level timing constraints.
#
# Ported from tt-oca-hw's block_flow_customizations/{global.clock_periods.tcl,
# sep/sep.clock_defines.tcl} and validated against the `sep` top-level port
# list (hw/sys/sep/rtl/sep.sv). All top-level port references below matched
# the current RTL with no renames.
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Known limitation, called out explicitly:
#   - The entropy clock-tree section below (ENTROPY_ROSC_CLK /
#     ENTROPY_SHARED_RO / per-tap generated clocks) targets post-synthesis
#     standard-cell instances by hierarchical path and by cell reference name
#     (`ref_name == gdffqb`, a toggle-flop primitive from the ported source's
#     original target cell library). That cell does not exist in the IHP
#     SG13G2 library this repo currently targets, and none of these `get_pins`
#     / `get_cells` lookups resolve pre-synthesis. `entropy_source` inside
#     `sep_crypto` is currently blackboxed per the ported source's own note,
#     so this section is kept as documentation of the intended clock topology
#     for whichever technology/EDA flow eventually implements it, not as a
#     constraint that resolves against this repo's RTL or PDK today.
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

create_clock -add -name SEPCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_i"]
create_clock -add -name WDTCLK            -period $clock_periods(WDTCLK_PERIOD)                [get_ports "clk_wdt_i"]
create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_tck"]

# OTBN PKA memories (have clock output in request struct)
create_generated_clock [get_ports sep_crypto_pka_imem_sram_req*clk] -name SEPCLK_PKA_IMEM -master_clock SEPCLK -divide_by 1 -source [get_ports "clk_i"] -combinational
create_generated_clock [get_ports sep_crypto_pka_dmem_sram_req*clk] -name SEPCLK_PKA_DMEM -master_clock SEPCLK -divide_by 1 -source [get_ports "clk_i"] -combinational

# feedthrough clock for any async input/outputs
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)

# Entropy clocks below are non-functional; entropy_source is currently blackboxed.
# See the "Known limitation" note in the file header: these get_pins/get_cells
# lookups target post-synthesis cells in the ported source's original target
# library and will not resolve against this repo's RTL or PDK.

# entropy_source sample-clock tree (egen/sclk): a length-109 shared ring oscillator
# plus one 5-stage ripple divider per generator. Each divider is fed by a mux between
# the external sample clock (ENTROPY_ROSC_CLK) and the shared RO, so every divider tap
# acts as a clock and is declared from both sources. Divide ratio is immaterial for
# CDC; only the source-clock relationship matters.
# shared ring oscillator output buffer pin
set entropy_shared_ro_pin [get_pins "sep_crypto/u_entropy_source/egen/sclk/shared_ro/fbf/z_o"]

# entropy_source ring-oscillator sample clock
create_clock -add -name ENTROPY_ROSC_CLK  -period $clock_periods(ENTROPY_ROSC_PERIOD) [get_ports "entropy_rosc_sample_clk_i"]

# entropy_source internal shared ring-oscillator clock
create_clock -add -name ENTROPY_SHARED_RO -period $clock_periods(ENTROPY_SHARED_RO_PERIOD) $entropy_shared_ro_pin

# all toggle-flop cells once; each divider's taps are selected by path below
set entropy_gdffqb [lsort -dictionary [get_object_name [get_cells -hierarchical -filter "ref_name == gdffqb"]]]

# one generated clock per divider tap from each source, numbered in stamping order
set entropy_tap_idx 0
foreach entropy_tap_cell [lsearch -all -inline -glob $entropy_gdffqb {*egen/sclk/g_ecmplx*u_sample_clk_divider*u_div_ff}] {
    set entropy_tap_pin [get_pins "${entropy_tap_cell}/q_o/Q"]
    create_generated_clock -add -name ENTROPY_SCLK_FROM_ROSC_${entropy_tap_idx}      -master_clock ENTROPY_ROSC_CLK  -divide_by 2 -source [get_ports "entropy_rosc_sample_clk_i"] $entropy_tap_pin
    create_generated_clock -add -name ENTROPY_SCLK_FROM_SHARED_RO_${entropy_tap_idx} -master_clock ENTROPY_SHARED_RO -divide_by 2 -source $entropy_shared_ro_pin $entropy_tap_pin
    incr entropy_tap_idx
}

# debug monitor ripple divider (dbg/u_ripple_divider): observability only -- it divides a
# debug-selected internal signal off-chip via signal_monitor_o, never into functional logic.
# The source is a dynamic debug mux, so declare each tap as its own clock and keep the whole
# divider in one async group, isolated from the functional clocks.
set entropy_dbg_tap_idx 0
foreach entropy_dbg_cell [lsearch -all -inline -glob $entropy_gdffqb {*dbg/u_ripple_divider*u_div_ff}] {
    create_clock -add -name ENTROPY_DBG_MON_${entropy_dbg_tap_idx} -period $clock_periods(ENTROPY_ROSC_PERIOD) [get_pins "${entropy_dbg_cell}/q_o/Q"]
    incr entropy_dbg_tap_idx
}

# the source mux passes the external clock or the shared RO into each divider, never both,
# so they are exclusive at every mux. Across generators the two families are not strictly
# exclusive (one generator can run external while another runs shared), but they never
# converge anywhere outside these muxes, so grouping each master plus its taps as
# logically_exclusive only suppresses analysis where the two sources actually mux -- safe
set_clock_groups -logically_exclusive \
    -group [concat {ENTROPY_ROSC_CLK}  [get_object_name [get_clocks "ENTROPY_SCLK_FROM_ROSC_*"]]] \
    -group [concat {ENTROPY_SHARED_RO} [get_object_name [get_clocks "ENTROPY_SCLK_FROM_SHARED_RO_*"]]]

set_clock_groups -asynchronous \
    -group {SEPCLK SEPCLK_PKA_IMEM SEPCLK_PKA_DMEM}\
    -group {WDTCLK}\
    -group {JTAG_TCK}\
    -group [concat {ENTROPY_ROSC_CLK}  [get_object_name [get_clocks "ENTROPY_SCLK_FROM_ROSC_*"]]]\
    -group [concat {ENTROPY_SHARED_RO} [get_object_name [get_clocks "ENTROPY_SCLK_FROM_SHARED_RO_*"]]]\
    -group [get_object_name [get_clocks "ENTROPY_DBG_MON_*"]]\
    -group {ck_feedthru}


########################################################
# Input and Output delays
########################################################

# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports rst_ni] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dbg_rstb_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports wdt_rst_ni] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports sep_reset_n_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports wdt_timer_rst_req_o] -add_delay

# JTAG
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tms] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdi] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports jtag_trst_n] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdo] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdoEn] -add_delay

# OTP debug AXI-Lite interface
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axil_sep_otp_jtag_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axil_sep_otp_jtag_resp_o*}] -add_delay

# MPC debug interface (async)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_debug_halt_req] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_debug_run_req] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_reset_run_req] -add_delay

# CPU halt/run interface (async)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports i_cpu_halt_req] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports i_cpu_run_req] -add_delay

# JTAG SEP reset control overrides (TCK domain)
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.val*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.ovrd*}] -add_delay

# Test
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay

# Boot sequence done
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# DMI interface
# - only SEPCLK because there is no internal synchronization like the mpc or cpu_halt
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_core_enable] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_enable] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_en] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_wr_en] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_addr*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_wdata*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_rdata*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_active] -add_delay

# CPU trace
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_trace*}] -add_delay

# CPU configuration inputs
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {rst_vec*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {jtag_id*}] -add_delay

# Interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports timer_int] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports soft_int] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {extintsrc_req*}] -add_delay

# SEP memories
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_tcm_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_tcm_rsp_i*}] -add_delay

# Scratchpad SRAM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_sram_req*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_sram_rsp*}] -add_delay

# Boot ROM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_req*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_rsp*}] -add_delay

# Key Manager memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_rsp_i*}] -add_delay

# Crypto PKA memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_imem_sram_req*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_imem_sram_rsp*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_dmem_sram_req*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_dmem_sram_rsp*}] -add_delay

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
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_trng_irq_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_trng_alarm_i] -add_delay

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

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports spi_irq_i] -add_delay

# LC state
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lc_state_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {feat_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports security_disable_o] -add_delay

# Mailbox interrupts
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smc_mailbox_interrupt_o*}] -add_delay

# Fuse sense status
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports smc_fuse_sense_done_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports sep_fuse_sense_done_o] -add_delay

# Straps
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {sep_straps_i*}] -add_delay

# AXI extension interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axi_extension_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axi_extension_axi_resp_i*}] -add_delay

# SMC address configuration
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smc_global_base_addr_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smc_region_size_i*}] -add_delay

# SEP aperture configuration
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_global_base_addr_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_region_size_o*}] -add_delay

# External debug bus
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_debug_bus_o*}] -add_delay
