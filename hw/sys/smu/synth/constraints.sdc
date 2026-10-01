# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMU (System Management Unit) block-level timing constraints.
#
# SMU is the top-level integration wrapper for SMC (System Management
# Controller), DTP (Debug and Trace Processor), and SEP (Secure Execution
# Processor, optional via the `SEP` parameter).
#
# Clock periods, generated clocks, clock groups, and I/O delays for every
# `smu` top-level port, validated against the `smu` top-level port list
# (hw/sys/smu/rtl/smu.sv) and its DTP/SMC/SEP sub-instances.
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2/abc.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Subcomponent hierarchy mode: this file supports a `smu_sam_flow` switch,
# shared by synth / CDC / RDC signoff.
#   smu_sam_flow == 0 (default, synth): SMC/DTP/SEP RTL is fully present, so
#     constraints reaching INTO subcomponent hierarchy (the AVS clock-mux /
#     divider pins inside u_smc/...) are applied. This is the mode relevant
#     to the current RTL-only flow in this repo.
#   smu_sam_flow == 1 (CDC/RDC): subcomponents are blackboxed and replaced by
#     signoff abstract models (SAM); those into-hierarchy pins do not exist,
#     so the full-hierarchy block is skipped and a simpler feedthrough model
#     is used instead. Not exercised by this repo today, kept for parity
#     with any future SAM-based signoff flow.
#
# Caveats, called out explicitly:
#   - `sep_crypto_entropy_req_o*` / `sep_crypto_entropy_rsp_i*` are commented
#     out below: no generic SEP crypto/entropy passthrough is exposed at the
#     current `smu` top level in this RTL (SEP only surfaces the PKA
#     imem/dmem SRAM and Key Manager ROM/SRAM interfaces).
#   - `sep_security_disable_i` is commented out below: `sep_security_disable`
#     is purely an internal net here (driven by `u_sep.security_disable_o`,
#     consumed by `u_smc.sep_security_disable_i`), not a top-level port.
#   - I/O delays are added below for real `smu` top-level ports with no
#     matching constraint elsewhere: `smc_global_base_o*`,
#     `sep_global_base_o*`, `sep_region_size_o*`, `gpio_interrupt_o*`,
#     `uart_interrupt_o*`, `i3c_dat_mem_sink_o*`, `i3c_dct_mem_sink_o*`,
#     `jtag_ic_reset_ext_o*`, and `sep_ext_interrupts_i`.
#   - The `AVS_DIV_CLK_Q_FROM_*` generated clocks below target the `div_clk`
#     register inside `prim_prog_clk_div_posedge` (reached via
#     `u_smc/u_smc_peripherals/u_avsbus_controller/...`) by name. In this RTL
#     that register is a plain `always_ff`-inferred flop (no discrete
#     primitive instance called `div_clk`), so the pin only resolves
#     post-synthesis once technology mapping assigns it a cell name; it will
#     not resolve against the elaborated RTL.
#   - CDC crossings are bounded in two layers, both included from this file.
#     `set_async_clock_groups` below declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `smu_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. This is separate from the
#     CDC/RDC signoff notes above, which concern how individual crossings are
#     modeled or waived, not how they are bounded. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
#   - `smu_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
#     It is produced once, offline, against an elaborated design and checked
#     in; nothing discovers instances when this file is read. Its paths and
#     clock names are OCAH's, so instantiating this block deeper in a
#     hierarchy or driving it from differently named clocks needs no edit
#     here -- set `::cdc_hier_prefix` and `::cdc_clock_alias` before sourcing
#     it. Regeneration, which runs in the closed synthesis flow, is needed
#     only when the block is reconfigured such that the set of CDC elements
#     changes: the file then goes stale silently, since no prefix can supply
#     constraints for elements it never listed.
#     It is a full-hierarchy enumeration: under the SAM flow the AVS clocks do
#     not exist, and the calls naming them warn and are skipped.
#     See "CDC Timing Constraints" in the Integrator Guide.
#-----------------------------------------------------------------------------

# Directory holding this file, so the CDC collateral below resolves regardless
# of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smu/synth]
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

# ---------------------------------------------------------------------------
# Subcomponent hierarchy mode (see file header).
# ---------------------------------------------------------------------------
if {![info exists smu_sam_flow]} { set smu_sam_flow 0 }
set smu_full_hier [expr {!$smu_sam_flow}]

##################
# CLOCK STAMPINGS
##################

create_clock -add -name REFCLK            -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name SMUCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_smu_i"]
create_clock -add -name PERIPHERALCLK     -period $clock_periods(PERIPHERALCLK_PERIOD)         [get_ports "clk_periph_i"]
create_clock -add -name TELEMETRYCLK      -period $clock_periods(TELEMETRYCLK_PERIOD)          [get_ports "clk_telemetry_i"]
create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"]

# JTAG STAP generated clocks (TCK outputs from DTP)
create_generated_clock [get_ports {jtag_stap_io_host_tap_ctrl_o*tck*}] \
    -name JTAG_STAP_IO_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

# Extra STAP TCK outputs (parameterized array - will match 0 or more ports)
create_generated_clock [get_ports {jtag_stap_extra_host_tap_ctrl_o*tck*}] \
    -name JTAG_STAP_EXTRA_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational \
    -add

# JTAG Scan Control (jtag_scan_ctrl_t) generated clocks
create_generated_clock [get_ports {jtag_bsr_host_scan_ctrl_o*tck*}] \
    -name JTAG_BSR_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_stap_host_scan_ctrl_o*tck*}] \
    -name JTAG_STAP_SCAN_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_dfd_host_scan_ctrl_o*tck*}] \
    -name JTAG_DFD_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_dft_secure_host_scan_ctrl_o*tck*}] \
    -name JTAG_DFT_SECURE_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_dft_host_scan_ctrl_o*tck*}] \
    -name JTAG_DFT_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

# memories
# The SMC SRAM/cache/ROM interface output clocks are defined and signed off
# INSIDE the SMC block; at the SMU boundary under a SAM (blackboxed) flow they
# would be unconstrained and undriven, so only stamp them when SMC/DTP/SEP RTL
# is fully present.
if {$smu_full_hier} {
create_generated_clock [get_ports smc_rom_intf_req_o*clk] -name SMUCLK_ROM -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_scratch_ram_intf_req_o?0*clk]  -name SMUCLK_RAM0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?1*clk]  -name SMUCLK_RAM1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?2*clk]  -name SMUCLK_RAM2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?3*clk]  -name SMUCLK_RAM3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?4*clk]  -name SMUCLK_RAM4  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?5*clk]  -name SMUCLK_RAM5  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?6*clk]  -name SMUCLK_RAM6  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?7*clk]  -name SMUCLK_RAM7  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?8*clk]  -name SMUCLK_RAM8  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?9*clk]  -name SMUCLK_RAM9  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?10*clk] -name SMUCLK_RAM10 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?11*clk] -name SMUCLK_RAM11 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?12*clk] -name SMUCLK_RAM12 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?13*clk] -name SMUCLK_RAM13 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?14*clk] -name SMUCLK_RAM14 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?15*clk] -name SMUCLK_RAM15 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?16*clk] -name SMUCLK_RAM16 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?17*clk] -name SMUCLK_RAM17 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?18*clk] -name SMUCLK_RAM18 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?19*clk] -name SMUCLK_RAM19 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?20*clk] -name SMUCLK_RAM20 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?21*clk] -name SMUCLK_RAM21 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?22*clk] -name SMUCLK_RAM22 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?23*clk] -name SMUCLK_RAM23 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?24*clk] -name SMUCLK_RAM24 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?25*clk] -name SMUCLK_RAM25 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?26*clk] -name SMUCLK_RAM26 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?27*clk] -name SMUCLK_RAM27 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?28*clk] -name SMUCLK_RAM28 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?29*clk] -name SMUCLK_RAM29 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?30*clk] -name SMUCLK_RAM30 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?31*clk] -name SMUCLK_RAM31 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?0*clk]  -name SMUCLK_ICACHE_TAG0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?1*clk]  -name SMUCLK_ICACHE_TAG1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?2*clk]  -name SMUCLK_ICACHE_TAG2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?3*clk]  -name SMUCLK_ICACHE_TAG3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?0*clk]  -name SMUCLK_ICACHE_DATA0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?1*clk]  -name SMUCLK_ICACHE_DATA1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?2*clk]  -name SMUCLK_ICACHE_DATA2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?3*clk]  -name SMUCLK_ICACHE_DATA3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?4*clk]  -name SMUCLK_ICACHE_DATA4  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?5*clk]  -name SMUCLK_ICACHE_DATA5  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?6*clk]  -name SMUCLK_ICACHE_DATA6  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?7*clk]  -name SMUCLK_ICACHE_DATA7  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?0*clk]  -name SMUCLK_DCACHE_TAG0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?1*clk]  -name SMUCLK_DCACHE_TAG1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?2*clk]  -name SMUCLK_DCACHE_TAG2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?3*clk]  -name SMUCLK_DCACHE_TAG3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?0*clk]  -name SMUCLK_DCACHE_DATA0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?1*clk]  -name SMUCLK_DCACHE_DATA1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?2*clk]  -name SMUCLK_DCACHE_DATA2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?3*clk]  -name SMUCLK_DCACHE_DATA3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
}

if {$smu_full_hier} {
############################
# AVS Clock Constraints
############################
# Note: For STA you need to care about the divided value (it is a programmable clock divider), but for CDC setup the fact its a divided value is all that matters
set avs_hier u_smc/u_smc_peripherals/u_avsbus_controller

# Refclk and periph clock both fed into a clock mux
# I will create a generated clock on the output of the clockmux for both possible sources
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 1 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 1 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"]

# Tell the tool the raw primaries stop at the mux output — the generated clocks take over from there
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    -clocks {REFCLK PERIPHERALCLK}

# Now the clock mux output is fed into a clock divider.
# Important RTL nuance: `prim_prog_clk_div_posedge` can also bypass the divider
# internally, so `avs_clock_o` may be launched either by the muxed parent clock
# or by the divided clock depending on mode.
# AVS clock when sourced from REFCLK (modes 10/11, DEFAULT)
create_generated_clock -add -name AVS_CLK_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"]

# AVS clock when sourced from PERIPHERALCLK (modes 00/01)
create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"]

# Same divided-clock intent on `u_clk_div/clk_o` (`pre_testmux_avs_clk`) so downstream
# STA does not flag an undeclared setup clock when propagation from u_div_clk_buf/clk_o
# alone does not reach the module output pin (prim_prog_clk_div_posedge).
create_generated_clock -add -name AVS_CLK_DIV_CLK_O_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/clk_o"]

create_generated_clock -add -name AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/clk_o"]

# Internal `div_clk` net (flop -> prim_clock_buf clk_i): stamped so downstream STA can
# resolve the setup clock looking for a PotentialRoot at `div_clk`, matching the
# energy already modeled at y_o.
create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_i"]

create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_i"]

# Toggle flop output (feeds u_div_clk_buf and u_postdiv_mux clk1_i). See the
# `div_clk/Q` caveat in the file header: this pin only exists post-synthesis,
# once technology mapping has assigned a concrete cell/pin name to the
# `always_ff`-inferred `div_clk` register in prim_prog_clk_div_posedge.
create_generated_clock -add -name AVS_DIV_CLK_Q_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/div_clk/Q"]

create_generated_clock -add -name AVS_DIV_CLK_Q_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/div_clk/Q"]

# apply generated clock to the final gpio output pin as well
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLK_FROM_REFCLK_GPIO \
    -master_clock AVS_CLK_FROM_REFCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLK_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"] \
    [get_ports {core2pad_o[49]}]

# Downstream AVS flops should resolve against `AVS_CLK_FROM_REFCLK` /
# `AVS_CLK_FROM_PERIPHERALCLK` families, which are `-logically_exclusive` below
# (only one premux source mode is active at a time).
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_clk_div/u_postdiv_mux/clk_o"] \
    -clocks {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK}

# These two can never be active simultaneously (muxed sources)
set_clock_groups -logically_exclusive \
    -group {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO} \
    -group {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
}

# SEP WDT clock
create_clock -add -name SEP_WDT_CLK -period $clock_periods(REFCLK_PERIOD) [get_ports "clk_sep_wdt_i"]

# I2C
# controller uses PERIPHCLK + a counter to create output SCL, there is no logic based on SCL output
# input SCL is also not used as a clock

# UART
# no clock divider used to generate UART baud rate

# EFUSE
# no clock divider in efuse interface controller

# I3C
# Controller uses PERIPHCLK + a counter to create output SCL, there is no logic based on SCL output
# input SCL is also not used as a clock

# feedthrough clock for any async input/outputs
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)

# Async groups: include the AVS divider clocks only with full hierarchy (synth);
# under a SAM flow they are not defined here.
set smu_refclk_async_grp {REFCLK}
set smu_periph_async_grp {PERIPHERALCLK}
if {$smu_full_hier} {
    set smu_refclk_async_grp {REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
    set smu_periph_async_grp {PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
}

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# Under the SAM flow the AVS groups collapse to the bare parents and the
# `-exclude` matches nothing, which is harmless. With full hierarchy the two AVS
# families are already `-logically_exclusive` above, so `-exclude` keeps them out
# of the asynchronous declaration -- a clock pair cannot carry both
# relationships. Their async relationship with every other clock is unaffected.
source [file join $ocah_flow_constraints_dir async_clock_groups.tcl]

set_async_clock_groups [list \
    $smu_refclk_async_grp \
    {SMUCLK SMUCLK_*} \
    $smu_periph_async_grp \
    {TELEMETRYCLK} \
    {JTAG_TCK JTAG_STAP_IO_TCK JTAG_STAP_EXTRA_TCK JTAG_BSR_TCK JTAG_STAP_SCAN_TCK JTAG_DFD_TCK JTAG_DFT_SECURE_TCK JTAG_DFT_TCK JTAG_TCK_*} \
    {SEP_WDT_CLK} \
    {ck_feedthru} \
] -exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}


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
# above; tied to '0 when SEP=0 but still SMUCLK-domain CSR outputs when SEP=1.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_global_base_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_region_size_o*}] -add_delay

# GPIO Data Signals
# Full hierarchy (synth): protocol-accurate I/O delays come from the GPIO
# Interface section below, which stamps SMCCLK / SPICLK_GPIO / PERIPHERALCLK
# / AVS-divider clocks on each GPIO bit.
# SAM flow (CDC/RDC): those internal protocol clocks live inside the SMC SAM
# and are not defined at the SMU boundary, so that section cannot apply there
# (it would error on SMCCLK / SPICLK_GPIO / AVS-divider clocks). At the SMU
# boundary the GPIO pads are async feedthroughs into the SAM, so stamp them
# with the ck_feedthru boundary clock instead. Without this the GPIO ports
# are unconstrained.
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
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports chiplet_is_primary_i] -add_delay
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
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_trng_irq_i] -add_delay

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
# These ports connect to an adopter-defined GPIO/padring implementation
# (passed through from SMC) and should not be modeled as a single
# `SMUCLK`-synchronous interface.
# - `lsio_interface_select_o` is mode-control / pad ownership information.
# - `core2pad_o` can carry mixed-domain protocol traffic, including clocks.
# - `pad2core_en_o` / `core2pad_en_o` are pad enable / ownership controls.
# Use a generic feedthrough model at the SMU top boundary, then add
# bit-specific clock intent separately where we know a GPIO is carrying a
# real protocol clock or other special signal. Bit assignments below mirror
# the SMC block-level GPIO constraints (same physical padring).
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {lsio_interface_select_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {core2pad_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {core2pad_en_o*}] -add_delay
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {pad2core_en_o*}] -add_delay

# UART TX outputs — launched by PERIPHERALCLK-domain UART IP (combinational pass-through)
# GPIO indices: 12 = UART[0].TX, 16 = UART[1].TX, 20 = UART[2].TX, 24 = UART[3].TX
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[12]}] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[16]}] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[20]}] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[24]}] -add_delay

# UART RTS outputs — launched by PERIPHERALCLK-domain UART IP (combinational pass-through)
# GPIO indices: 13 = UART[0].RTS, 17 = UART[1].RTS, 21 = UART[2].RTS, 25 = UART[3].RTS
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[13]}] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[17]}] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[21]}] -add_delay
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {core2pad_o[25]}] -add_delay

# UART RX pads — output is constant 0, pad output driver disabled (input-only pads)
# GPIO indices: 11 = UART[0].RX, 15 = UART[1].RX, 19 = UART[2].RX, 23 = UART[3].RX
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[11]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[15]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[19]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[23]}] -add_delay

# UART CTS pads — output is constant 0, pad output driver disabled (input-only pads)
# GPIO indices: 14 = UART[0].CTS, 18 = UART[1].CTS, 22 = UART[2].CTS, 26 = UART[3].CTS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[14]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[18]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[22]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMUCLK] [get_ports {core2pad_o[26]}] -add_delay

# Reserved
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {core2pad_o[56]}] -add_delay

# System timer / OCTS — outputs driven from SMUCLK-domain timer (GPIO table).
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {core2pad_o[58]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {core2pad_o[59]}] -add_delay


# `pad2core_i` is a mixed-domain GPIO boundary. Apply the generic `ck_feedthru`
# feedthrough model only to bits whose source clock is not known at this level,
# and override bits that carry a real protocol clock or are source-synchronous
# to one so CDC/STA analyze them in their actual domain.
#
# Pinout reference (authoritative): doc/integrator/meta/ocah_gpio_table.adoc
# Padring connectivity is adopter-defined and lives outside this repo; the bit
# assignments below are cross-checked against the pinout table only.
#
# SPI clock-domain `pad2core_i` bits, per the adoc pinout:
#
#   Bit | Pinout function
#   ----+----------------------------
#   [0] | SPI.DATA[0]
#   [1] | SPI.DATA[1]
#   [2] | SPI.DATA[2]
#   [3] | SPI.DATA[3]
#   [4] | SPI.DATA[4]
#   [5] | SPI.DATA[5]
#   [6] | SPI.DATA[6]
#   [7] | SPI.DATA[7]
#   [9] | SPI.CLK (would need a generated clock similar to the SMC block-level
#       | SPICLK_GPIO; not re-derived here since SMU does not expose the SPI
#       | clock port directly -- excluded from the generic bucket below)
#   [10]| SPI.DQS
#   [54]| SPI DQS Loopback
#
# SMC (via SEP cdns_spi) is the SPI master and emits the SPI clock on
# core2pad_o[9]; the external flash launches DATA[7:0] and DQS back source-
# synchronous to that clock. At the SMU level there is no local SPICLK port to
# re-derive a generated clock from (unlike the SMC block-level SDC, which sees
# `spi_clk_i` directly), so these bits fall back to the generic ck_feedthru
# model below rather than being excluded into a dedicated SPICLK group.
set spi_pad2core_bits [get_ports {pad2core_i[0] pad2core_i[1] pad2core_i[2] pad2core_i[3] \
                                  pad2core_i[4] pad2core_i[5] pad2core_i[6] pad2core_i[7] \
                                  pad2core_i[9] pad2core_i[10] pad2core_i[54]}]

# I2C pad inputs (GPIO 37–48): three controllers × {SCL, SDA, SMBus Alert, SMBus Suspend}.
# Pinout: doc/integrator/meta/ocah_gpio_table.adoc. Open-drain bus lines are sampled by
# `i2c_core` synchronizers clocked from PERIPHERALCLK; modeling launch on PERIPHERALCLK
# aligns CDC/STA with the capture clock.
set i2c_pad2core_bits [get_ports {pad2core_i[37] pad2core_i[38] pad2core_i[39] pad2core_i[40] \
                                  pad2core_i[41] pad2core_i[42] pad2core_i[43] pad2core_i[44] \
                                  pad2core_i[45] pad2core_i[46] pad2core_i[47] pad2core_i[48]}]

# System timer / OCTS pad inputs (GPIO 58–59): sampled by `system_timer_octs` on SMUCLK.
set system_timer_pad2core_bits [get_ports {pad2core_i[58] pad2core_i[59]}]

# SPI chip select input pad (GPIO 8) — SPI controller domain (SMUCLK register plane).
set gpio_spi_cs_pad [get_ports {pad2core_i[8]}]

# UART straps GPIO 11–26 (RX/TX/RTS/CTS): consumed by PERIPHERALCLK UART IP / padring.
set gpio_uart_pad2core [get_ports {pad2core_i[11] pad2core_i[12] pad2core_i[13] pad2core_i[14] \
    pad2core_i[15] pad2core_i[16] pad2core_i[17] pad2core_i[18] pad2core_i[19] pad2core_i[20] \
    pad2core_i[21] pad2core_i[22] pad2core_i[23] pad2core_i[24] pad2core_i[25] pad2core_i[26]}]

# AVS CLOCK + MDATA observe inputs (GPIO 49–50) — dual launch vs divider clocks (same pattern as SDATA [51]).
set gpio_avs_clk_mdata [get_ports {pad2core_i[49] pad2core_i[50]}]

# Thermal / isolate (52–53); PLL obs / PVT / straps (55–57); reserved / unbonded (61–67).
set gpio_misc_a [get_ports {pad2core_i[52] pad2core_i[53]}]
set gpio_misc_b [get_ports {pad2core_i[55] pad2core_i[56] pad2core_i[57]}]
set gpio_misc_c [get_ports {pad2core_i[61] pad2core_i[62] pad2core_i[63] pad2core_i[64] pad2core_i[65] pad2core_i[66] pad2core_i[67]}]

# Bits excluded from generic ck_feedthru: SPI data/DQS/CLK/CS [0:7,9,10,54], I2C [37:48],
# AVS SDATA [51], system timer [58:59], UART block [11:26], AVS clk/mdata [49:50],
# misc [8] [52:53] [55:57] [61:67].
set pad2core_excluded $spi_pad2core_bits
set pad2core_excluded [add_to_collection $pad2core_excluded $i2c_pad2core_bits]
set pad2core_excluded [add_to_collection $pad2core_excluded [get_ports {pad2core_i[51]}]]
set pad2core_excluded [add_to_collection $pad2core_excluded $system_timer_pad2core_bits]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_spi_cs_pad]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_uart_pad2core]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_avs_clk_mdata]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_a]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_b]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_c]
set pad2core_generic [remove_from_collection [get_ports {pad2core_i*}] $pad2core_excluded]

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] $pad2core_generic -add_delay

# SPI data / DQS / DQS-loopback / clock inputs: no local SPICLK to reference at
# the SMU boundary (see note above), so fall back to the ck_feedthru model.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] $spi_pad2core_bits -add_delay

# SPI CS pad input (GPIO 8).
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]        -clock [get_clock SMUCLK] $gpio_spi_cs_pad -add_delay

# I2C pads — consumed by PERIPHERALCLK-domain synchronizers and receivers.
set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i2c_pad2core_bits -add_delay

# UART GPIO 11–26 — PERIPHERALCLK UART slice / padring.
set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $gpio_uart_pad2core -add_delay

# GPIO [51] AVS.SDATA — flops in AVS divider clock domain (`avs_sdata_capture`, interrupt detect).
# Legal mux modes match AVS GPIO clock intent on core2pad_o[49].
set avs_sdata_pad [get_ports {pad2core_i[51]}]
set_input_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_REFCLK] $avs_sdata_pad -add_delay
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK] $avs_sdata_pad -add_delay

# AVS CLOCK + MDATA observe (GPIO 49–50) — same legal AVS clock roots as SDATA.
set_input_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_REFCLK] $gpio_avs_clk_mdata -add_delay
set_input_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK] $gpio_avs_clk_mdata -add_delay

set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] $system_timer_pad2core_bits -add_delay

# Misc GPIO inputs — thermal/isolate and observability (SMUCLK); reserved/unbonded (generic feedthru).
set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [add_to_collection $gpio_misc_a $gpio_misc_b] -add_delay
set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] $gpio_misc_c -add_delay
########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir smu_cdc_max_delay.tcl]
