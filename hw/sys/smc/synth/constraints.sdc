# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC (System Management Controller) block-level timing constraints.
#
# Clock periods, generated clocks, clock groups, and I/O delays for every
# `smc` top-level port, validated against the `smc` top-level port list
# (hw/sys/smc/rtl/smc.sv) and the AVS clock-mux/divider hierarchy
# (hw/ip/avsbus_controller/rtl/avsbus_controller.sv).
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2/abc.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Caveats, called out explicitly:
#   - `rst_primary_periph_clk_no` is a real `smc` top-level port; its I/O
#     delay below is modeled on its sibling reset outputs.
#   - The `AVS_DIV_CLK_Q_FROM_*` generated clocks below target the `div_clk`
#     register inside `prim_prog_clk_div_posedge` by name. In this RTL that
#     register is a plain `always_ff`-inferred flop (no discrete primitive
#     instance called `div_clk`), so the pin only resolves post-synthesis
#     once technology mapping assigns it a cell name; it will not resolve
#     against the elaborated RTL.
#   - CDC crossings are bounded in two layers, both included from this file.
#     `set_async_clock_groups` below declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `smc_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
#   - `smc_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
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
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smc/synth]
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

create_clock -add -name REFCLK                  -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name SMCCLK                  -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_smc_i"]
create_clock -add -name PERIPHERALCLK           -period $clock_periods(PERIPHERALCLK_PERIOD)         [get_ports "clk_periph_i"]
create_clock -add -name TELEMETRYCLK            -period $clock_periods(TELEMETRYCLK_PERIOD)          [get_ports "clk_telemetry_i"]
create_clock -add -name JTAG_TCK                -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "smc_cpu_jtag_TCK_i"]

# memories
create_generated_clock [get_ports smc_rom_intf_req_o*clk] -name SMCCLK_ROM -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

# Scratch RAM clocks
set scratch_ram_clk_ports [lsort -dictionary [get_object_name [get_ports {smc_scratch_ram_intf_req_o*clk}]]]
set scratch_ram_clk_idx 0
foreach scratch_ram_clk_port $scratch_ram_clk_ports {
    create_generated_clock [get_ports $scratch_ram_clk_port] -name SMCCLK_RAM${scratch_ram_clk_idx} -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
    incr scratch_ram_clk_idx
}

create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*0*clk]  -name SMCCLK_ICACHE_TAG0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*1*clk]  -name SMCCLK_ICACHE_TAG1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*2*clk]  -name SMCCLK_ICACHE_TAG2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*3*clk]  -name SMCCLK_ICACHE_TAG3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*0*clk]  -name SMCCLK_ICACHE_DATA0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*1*clk]  -name SMCCLK_ICACHE_DATA1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*2*clk]  -name SMCCLK_ICACHE_DATA2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*3*clk]  -name SMCCLK_ICACHE_DATA3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*4*clk]  -name SMCCLK_ICACHE_DATA4  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*5*clk]  -name SMCCLK_ICACHE_DATA5  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*6*clk]  -name SMCCLK_ICACHE_DATA6  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*7*clk]  -name SMCCLK_ICACHE_DATA7  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*0*clk]  -name SMCCLK_DCACHE_TAG0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*1*clk]  -name SMCCLK_DCACHE_TAG1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*2*clk]  -name SMCCLK_DCACHE_TAG2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*3*clk]  -name SMCCLK_DCACHE_TAG3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*0*clk]  -name SMCCLK_DCACHE_DATA0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*1*clk]  -name SMCCLK_DCACHE_DATA1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*2*clk]  -name SMCCLK_DCACHE_DATA2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*3*clk]  -name SMCCLK_DCACHE_DATA3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational


# ----------------------
# AVS Clock Constraints
# ----------------------
# Note: For STA you need to care about the divided value (it is a programmable clock divider), but for CDC setup the fact its a divided value is all that matters
set avs_hier u_smc_peripherals/u_avsbus_controller

# Stamp each source's generated clock on its gater output.
# `prim_ag_clk_mux` takes the peripheral clock on clk0_i and the reference clock
# on clk1_i, so clk1_gate is the REFCLK branch and clk0_gate the PERIPHERALCLK one.
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 1 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk1_gate/clk_o"]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 1 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk0_gate/clk_o"]

# Raw primaries stop at their gater outputs before the OR
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk1_gate/clk_o"] \
    -clocks {REFCLK}
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk0_gate/clk_o"] \
    -clocks {PERIPHERALCLK}

# Now the clock mux output is fed into a clock divider.
# For CDC setup, the exact divide ratio is less important than the
# source-clock relationship, so the fixed `/4` is acceptable here.
# Important RTL nuance: `prim_prog_clk_div_posedge` can also bypass the divider
# internally, so `avs_clock_o` may be launched either by the muxed parent clock
# or by the divided clock depending on mode.
# AVS clock when sourced from REFCLK (modes 10/11, DEFAULT)
create_generated_clock -add -name AVS_CLK_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"]

# AVS clock when sourced from PERIPHERALCLK (modes 00/01)
create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"]

# Same divided-clock intent on `u_clk_div/clk_o` (`pre_testmux_avs_clk`) so downstream
# STA does not flag an undeclared setup clock when propagation from u_div_clk_stdbuf/y_o
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

# Internal `div_clk` net (flop -> prim_stdbuf a_i): stamped so downstream STA can
# resolve the setup clock looking for a PotentialRoot at `div_clk`, matching the
# energy already modeled at y_o.
create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 4 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/a_i"]

create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/a_i"]

# Toggle flop output (feeds u_div_clk_stdbuf and u_postdiv_mux clk1_i). See the
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
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLK_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"] \
    [get_ports {core2pad_o[49]}]

# CDC-only modeling: collapse the AVS-clock domain attribution downstream of
# the programmable divider. Inside `prim_prog_clk_div_posedge`, the bypass
# path (`u_postdiv_mux/clk0_i`) lets `AVS_CLKMUX_OUTPUT_*` propagate through to
# `clk_o`, while the divided path stamps `AVS_CLK_FROM_*` at `u_div_clk_stdbuf/y_o`. The
# net result is every downstream AVS-domain flop is attributed FOUR clocks
# (mux-out + divided, each from REFCLK and PERIPHERALCLK roots), which a CDC
# tool would otherwise report as multi-domain convergence at `interrupt_o`,
# resync-flop outputs, etc., and as a multi-synchronized reset for the
# APB-clock reset that fans into the clear/resync handshake blocks.
#
# For CDC, the bypass and divided modes are functionally the SAME AVS clock
# (just different frequencies), so we stop the upstream `AVS_CLKMUX_OUTPUT_*`
# clocks at the post-divider mux output. Downstream AVS-domain flops then
# see only `AVS_CLK_FROM_REFCLK` / `AVS_CLK_FROM_PERIPHERALCLK`, which are
# already declared `-logically_exclusive` below (only one source-mode is
# active at a time).
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_clk_div/u_postdiv_mux/clk_o"] \
    -clocks {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK}

# These two can never be active simultaneously (muxed sources)
set_clock_groups -logically_exclusive \
    -group {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO} \
    -group {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}

# SPI
create_clock -add -name SPICLK            -period $clock_periods(SPICLK_PERIOD)                [get_ports "spi_clk_i"]

create_generated_clock [get_ports {pad2core_i[9]}] -name SPICLK_IN_GPIO  -master_clock SPICLK -divide_by 1 -source [get_ports "spi_clk_i"]
create_generated_clock [get_ports {core2pad_o[9]}] -name SPICLK_OUT_GPIO -master_clock SPICLK -divide_by 1 -source [get_ports "spi_clk_i"]

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

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# The two AVS families are already `-logically_exclusive` above, so `-exclude`
# keeps them out of the asynchronous declaration -- a clock pair cannot carry
# both relationships. Their async relationship with every other clock is
# unaffected.
source [file join $ocah_flow_constraints_dir async_clock_groups.tcl]

set_async_clock_groups {
    {REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
    {SMCCLK SMCCLK_*}
    {PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
    {SPICLK SPICLK_IN_GPIO SPICLK_OUT_GPIO}
    {TELEMETRYCLK}
    {JTAG_TCK}
    {ck_feedthru}
} -exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}


########################################################
# Input and Output delays
########################################################

# GPIO input and output delays
# -> handled below in the "GPIO Interface" section

# resets
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports powergood_i] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports powergood_stable_o] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cold_ni] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_cold_stable_ref_clk_no] -add_delay

set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_primary_ref_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports rst_primary_smc_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports rst_wdt_smc_clk_no] -add_delay
# `rst_primary_periph_clk_no` is a real `smc` top-level output; constrained
# on PERIPHERALCLK to match its name, following the same 50%-period margin
# pattern as its sibling reset outputs.
set_output_delay [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports rst_primary_periph_clk_no] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cool_n_from_pin_i] -add_delay

# AXI / AXI-Lite interfaces
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sys_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sys_axi_in_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {jtag_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {jtag_axi_in_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_smc_otp_jtag_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_smc_otp_jtag_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sep_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sep_axi_in_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {output_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {output_axi_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_dtp_csr_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_dtp_csr_resp_i*}] -add_delay

# The GPIO padring, PLL, PVT and eFuse SHIM control planes all reach the adopter
# through smc_external below; they are SMC-domain by contract. Adopter-specific
# refclk logic behind that window must add any local CDC explicitly rather than
# reinterpret these top-level ports as REFCLK ports.
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_external_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_shim_command_resp_i*}] -add_delay

# telemetry
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports rst_telemetry_ni] -add_delay

set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atdata_i*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atready_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atvalid_i*}] -add_delay
# NOTE: This is driven by SMCCLK, is it supposed to be?
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {telemetry_afvalid_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afready_i*}] -add_delay

# WDT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_wdt_first_timeout_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_wdt_second_timeout_o] -add_delay

# interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ext_interrupts_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sep_mailbox_interrupts_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports sep_wdt_reset_n_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_ext_mailbox_interrupts_o*}] -add_delay

# efuse
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {shadow_regs_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_fuse_sense_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_fuse_reset_n_delayed_o] -add_delay

# boot stall
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports boot_stall_jtag_ovrd_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports boot_stall_jtag_val_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports boot_stall_combined_o] -add_delay

# DFT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports skip_mem_repair_o] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# LC
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {lc_state_i*}] -add_delay

# RAS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_cluster_ded_o] -add_delay

# NDM
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ndmreset_request_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_ndmreset_process_o*}] -add_delay

# reset unit
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cfg_flr_pf_active_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {isolate_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ss_reset_complete_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {ss_config_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {ss_reset_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports sync_irq_o] -add_delay

# memory
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_rom_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMCCLK] [get_ports {smc_rom_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_scratch_ram_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_scratch_ram_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_icache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_icache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_icache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_icache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_dcache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_dcache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_dcache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_dcache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [get_ports {trace_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {trace_mem_resp_i*}] -add_delay

# OCTS
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports chiplet_is_primary_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {timer_count_o*}] -add_delay

# DFD
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports xtrigger_ss_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports xtrigger_ss_o] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_debug_bus_i] -add_delay

# Test
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay


# DFT
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mem_repair_done_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mem_repair_success_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mem_repair_abort_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mbist_done_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mbist_pass_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mbist_abort_i] -add_delay

# SPI signals below are more relaxed than the typical 50% delay because they just pass through SMC

# SPI enable (controlled by internal registers)
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.4]       -clock [get_clock SMCCLK] [get_ports spi_enable_i] -add_delay

# SPI data and pad control signals
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_txd_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_clk_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_clk_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_dqs_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_dqs_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_dq_ie_n_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_dq_oe_n_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_oepad_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_opad_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_iepad_i] -add_delay
set_output_delay [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_rxd_o*}] -add_delay
set_output_delay [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_rxds_o] -add_delay
set_output_delay [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_ipad_o] -add_delay

# I3C — data-memory read response bus (struct-flattened port names). Tied or driven
# from the memory controller in chip context; stamp PERIPHERALCLK for block CDC SETUP.
set i3c_dmem_ports [get_ports -quiet "i3c_dat_mem_src_i*"]
if {[sizeof_collection $i3c_dmem_ports] > 0} {
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dmem_ports -add_delay
    puts "INFO: set_input_delay PERIPHERALCLK on i3c_dat_mem_src_i* ([sizeof_collection $i3c_dmem_ports] ports)"
}

set i3c_dct_mem_ports [get_ports -quiet "i3c_dct_mem_src_i*"]
if {[sizeof_collection $i3c_dct_mem_ports] > 0} {
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dct_mem_ports -add_delay
    puts "INFO: set_input_delay PERIPHERALCLK on i3c_dct_mem_src_i* ([sizeof_collection $i3c_dct_mem_ports] ports)"
}

# SMC control/status signals
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_global_base_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_region_size_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_init_mem_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {cla_ext_action_custom_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports tdr_dbg_ctrl_clocks_stopped_by_cla_o] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports sep_security_disable_i] -add_delay

# For us its driven by captured straps | shadow reg, but for an adopter its hard to say. Should not assume anything about the source of this signal.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports smc_disable_sram_auto_init_i] -add_delay
# NOTE: clarify the intended launch/capture domain for `tdr_dbg_ctrl_clock_stop_en_i`.
# The current block-level model keeps this on `ck_feedthru` until the JTAG / TCK
# relationship is confirmed.
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports tdr_dbg_ctrl_clock_stop_en_i] -add_delay

set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TMS_i}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TDI_i}] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TDO_data_o}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_reset_i}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_mfr_id_i*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_part_number_i*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_version_i*}] -add_delay

set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_reset_ctrl_i.val*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_reset_ctrl_i.ovrd*}] -add_delay

########################################################
# GPIO Interface
########################################################
# These ports connect to an adopter-defined GPIO/padring implementation and
# should not be modeled as a single `SMCCLK`-synchronous interface.
# - `lsio_interface_select_o` is mode-control / pad ownership information.
# - `core2pad_o` can carry mixed-domain protocol traffic, including clocks.
# - `pad2core_en_o` / `core2pad_en_o` are pad enable / ownership controls.
# Use a generic feedthrough model at the SMC top boundary, then add bit-specific
# clock intent separately where we know a GPIO is carrying a real protocol
# clock or other special signal.
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
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[11]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[15]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[19]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[23]}] -add_delay

# UART CTS pads — output is constant 0, pad output driver disabled (input-only pads)
# GPIO indices: 14 = UART[0].CTS, 18 = UART[1].CTS, 22 = UART[2].CTS, 26 = UART[3].CTS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[14]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[18]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[22]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5] -clock [get_clock SMCCLK] [get_ports {core2pad_o[26]}] -add_delay


# Reserved
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {core2pad_o[56]}] -add_delay

# System timer / OCTS — outputs driven from SMCCLK-domain timer (GPIO table).
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {core2pad_o[58]}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {core2pad_o[59]}] -add_delay


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
#   [9] | SPI.CLK (generated clock SPICLK_GPIO — stamped above; excluded here
#       | to avoid re-adding an input delay)
#   [10]| SPI.DQS
#   [54]| SPI DQS Loopback
#
# SMC (via SEP cdns_spi) is the SPI master and emits the SPI clock on
# core2pad_o[9]; the external flash launches DATA[7:0] and DQS back source-
# synchronous to that clock. Those outputs are already stamped on `SPICLK`
# above, and `SPICLK` + `SPICLK_GPIO` share the same async clock group, so the
# pad-to-pad feedthrough is an intra-group synchronous path rather than a CDC
# crossing.
set spi_pad2core_bits [get_ports {pad2core_i[0] pad2core_i[1] pad2core_i[2] pad2core_i[3] \
                                  pad2core_i[4] pad2core_i[5] pad2core_i[6] pad2core_i[7] \
                                  pad2core_i[10] pad2core_i[54]}]

# I2C pad inputs (GPIO 37–48): three controllers × {SCL, SDA, SMBus Alert, SMBus Suspend}.
# Pinout: doc/integrator/meta/ocah_gpio_table.adoc. Open-drain bus lines are sampled by
# `i2c_core` synchronizers clocked from PERIPHERALCLK; modeling launch on PERIPHERALCLK
# aligns CDC/STA with the capture clock (same pattern as SPI pad2core bits on
# SPICLK_GPIO vs generic ck_feedthru).
set i2c_pad2core_bits [get_ports {pad2core_i[37] pad2core_i[38] pad2core_i[39] pad2core_i[40] \
                                  pad2core_i[41] pad2core_i[42] pad2core_i[43] pad2core_i[44] \
                                  pad2core_i[45] pad2core_i[46] pad2core_i[47] pad2core_i[48]}]

# System timer / OCTS pad inputs (GPIO 58–59): sampled by `system_timer_octs` on SMCCLK.
set system_timer_pad2core_bits [get_ports {pad2core_i[58] pad2core_i[59]}]

# SPI chip select input pad (GPIO 8) — SPI controller domain (SMCCLK register plane).
set gpio_spi_cs_pad [get_ports {pad2core_i[8]}]

# UART straps GPIO 11–26 (RX/TX/RTS/CTS): consumed by PERIPHERALCLK UART IP / padring.
set gpio_uart_pad2core [get_ports {pad2core_i[11] pad2core_i[12] pad2core_i[13] pad2core_i[14] \
    pad2core_i[15] pad2core_i[16] pad2core_i[17] pad2core_i[18] pad2core_i[19] pad2core_i[20] \
    pad2core_i[21] pad2core_i[22] pad2core_i[23] pad2core_i[24] pad2core_i[25] pad2core_i[26]}]

# AVS CLOCK + MDATA observe inputs (GPIO 49–50) — dual launch vs divider clocks (same pattern as SDATA [51]).
set gpio_avs_clk_mdata [get_ports {pad2core_i[49] pad2core_i[50]}]

# Thermal / isolate (52–53); PLL obs / PVT / straps (55–57); unbonded (61–64).
# `pad2core_i` is NUM_GPIO_WRAPS wide (61 bonded + 4 unbonded = 65), so 64 is the
# last bit. Pinout rows 65+ are dedicated JTAG/REFCLK pads, not GPIO bits.
set gpio_misc_a [get_ports {pad2core_i[52] pad2core_i[53]}]
set gpio_misc_b [get_ports {pad2core_i[55] pad2core_i[56] pad2core_i[57]}]
set gpio_misc_c [get_ports {pad2core_i[61] pad2core_i[62] pad2core_i[63] pad2core_i[64]}]

# Bits excluded from generic ck_feedthru: SPI data/DQS [0:7] [10] [54], SPI CS [8],
# SPICLK_GPIO [9], UART [11:26], I2C [37:48], AVS clk/mdata [49:50], AVS SDATA [51],
# thermal/isolate [52:53], system timer / boot stall [55:57], OCCP [58:59],
# unbonded [61:64]. The I3C bus bits [27:36] and reserved [60] keep the generic model.
set pad2core_excluded $spi_pad2core_bits
set pad2core_excluded [add_to_collection $pad2core_excluded $i2c_pad2core_bits]
set pad2core_excluded [add_to_collection $pad2core_excluded [get_ports {pad2core_i[9] pad2core_i[51]}]]
set pad2core_excluded [add_to_collection $pad2core_excluded $system_timer_pad2core_bits]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_spi_cs_pad]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_uart_pad2core]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_avs_clk_mdata]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_a]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_b]
set pad2core_excluded [add_to_collection $pad2core_excluded $gpio_misc_c]
set pad2core_generic [remove_from_collection [get_ports {pad2core_i*}] $pad2core_excluded]

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] $pad2core_generic -add_delay

# SPI data / DQS / DQS-loopback inputs: launched by the external flash
# synchronous to the SPI clock SMC emitted on core2pad_o[9].
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK_GPIO] $spi_pad2core_bits -add_delay

# SPI CS pad input (GPIO 8).
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]        -clock [get_clock SMCCLK] $gpio_spi_cs_pad -add_delay

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

set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] $system_timer_pad2core_bits -add_delay

# Misc GPIO inputs — thermal/isolate and observability (SMCCLK); reserved/unbonded (generic feedthru).
set_input_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [add_to_collection $gpio_misc_a $gpio_misc_b] -add_delay
set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5] -clock [get_clock ck_feedthru] $gpio_misc_c -add_delay


########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir smc_cdc_max_delay.tcl]
