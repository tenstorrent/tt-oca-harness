# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC clock stampings.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Reads $clock_periods(...); the sourcing flow
# populates that array first.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "smc_clocks.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

# Hierarchy-reusable: boundary constraints apply at block top only -- replayed under a
# parent (SMU) these nets carry the parent's clocks via ::cdc_clock_alias -- while the
# AVS clock tree re-anchors through cdc_inst. Identity when no parent has opted in.
if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}
# Boundary clocks: block-top only. At the parent these nets carry the parent's clocks.
if {[cdc_is_block_top]} {
create_clock -add -name REFCLK                  -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name SMCCLK                  -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_smc_i"]
create_clock -add -name PERIPHERALCLK           -period $clock_periods(PERIPHERALCLK_PERIOD)         [get_ports "clk_periph_i"]
create_clock -add -name TELEMETRYCLK            -period $clock_periods(TELEMETRYCLK_PERIOD)          [get_ports "clk_telemetry_i"]
create_clock -add -name JTAG_TCK                -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "smc_cpu_jtag_TCK_i"]
}

# Memory-interface output clocks: block-top only. The parent stamps its own
# identically shaped generated clocks on its own exported memory ports.
if {[cdc_is_block_top]} {
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
}

# AVS Clock Constraints
# ----------------------
# Note: For STA you need to care about the divided value (it is a programmable clock divider), but for CDC setup the fact its a divided value is all that matters
set avs_hier [cdc_inst u_smc_peripherals/u_avsbus_controller]

# `set_clock_sense` needs a leaf pin, and every pin on an RTL module boundary is
# hierarchical, so the stops below only apply once technology mapping has turned
# the gater and the post-divider mux into library cells. DC reports that failure
# without raising a Tcl error, so an unguarded call fails in silence -- hence the
# check. One gater pin stands for all of them: they become leaves together.
set avs_gate_cell [get_cells -quiet -of_objects \
    [get_pins -quiet "${avs_hier}/u_refclk_apbclk_mux/u_clk1_gate/clk_o"]]
set avs_mapped [expr { [sizeof_collection $avs_gate_cell] \
                       && [get_attribute -quiet $avs_gate_cell is_hierarchical] ne "true" }]

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
if { $avs_mapped } {
    set_clock_sense -stop_propagation \
        [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk1_gate/clk_o"] \
        -clocks {REFCLK}
    set_clock_sense -stop_propagation \
        [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk0_gate/clk_o"] \
        -clocks {PERIPHERALCLK}
} else {
    puts "INFO: smc_clocks: gater outputs are still hierarchical pins; the REFCLK and\
          PERIPHERALCLK clock-sense stops are not applied"
}

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
    -divide_by 4 \
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
if { [sizeof_collection [get_pins -quiet "${avs_hier}/u_clk_div/div_clk/Q"]] } {
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
} else {
    puts "INFO: smc_clocks: u_clk_div/div_clk/Q does not exist yet; AVS_DIV_CLK_Q_FROM_REFCLK\
          and AVS_DIV_CLK_Q_FROM_PERIPHERALCLK are not stamped"
}

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

# CDC-only modeling: collapse the AVS-clock domain attribution downstream of
# the programmable divider. Inside `prim_prog_clk_div_posedge`, the bypass
# path (`u_postdiv_mux/clk0_i`) lets `AVS_CLKMUX_OUTPUT_*` propagate through to
# `clk_o`, while the divided path stamps `AVS_CLK_FROM_*` at `u_div_clk_buf/clk_o`. The
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
if { $avs_mapped } {
    set_clock_sense -stop_propagation \
        [get_pins "${avs_hier}/u_clk_div/u_postdiv_mux/clk_o"] \
        -clocks {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK}
} else {
    puts "INFO: smc_clocks: u_postdiv_mux/clk_o is still a hierarchical pin; the AVS_CLKMUX_OUTPUT\
          clock-sense stop is not applied, so those clocks propagate downstream"
}

# These two can never be active simultaneously (muxed sources)
set_clock_groups -logically_exclusive \
    -group {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO} \
    -group {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}

# SPI
# SPICLK has no parent-level equivalent (at SMU, spi_clk_i is driven internally by SEP),
# so it is created at both levels: on the port at block top, on the instance pin above.
create_clock -add -name SPICLK            -period $clock_periods(SPICLK_PERIOD)                [cdc_port_or_pin "spi_clk_i"]

create_generated_clock [get_ports {pad2core_i[9]}] -name SPICLK_IN_GPIO  -master_clock SPICLK -divide_by 1 -source [cdc_port_or_pin "spi_clk_i"]
create_generated_clock [get_ports {core2pad_o[9]}] -name SPICLK_OUT_GPIO -master_clock SPICLK -divide_by 1 -source [cdc_port_or_pin "spi_clk_i"]

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
if {[cdc_is_block_top]} {
    create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)
}
