# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# smu.pad_boundary.tcl - SMU pad-boundary clocks and CDC constraints
#
# SMU's GPIO and entropy ports are top ports, so SMU is the block top for the pad
# constraints that SMC and SEP apply only at their own top (smc.pad_boundary.tcl,
# the GPIO clocks in smc_clocks.sdc, ENTROPY_ROSC_CLK in sep_clocks.sdc). This file
# states them on SMU's ports. smu.cdc_rdc.tcl sources it after the SMC and SEP
# replays, whose AVS and SPI clocks these generated clocks derive from, and before
# the async grouping. A parent of SMU constrains its own pads instead.
################################################################################

if { ![cdc_is_block_top] } {
    puts "INFO: smu.pad_boundary: skipped under prefix '$::cdc_hier_prefix'; the parent\
          constrains the pad boundary"
    return
}

set avs_hier u_smc/u_smc_peripherals/u_avsbus_controller

# The AVS clock leaves the chip on core2pad_o[49].
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

# The AVS source families stay logically exclusive with the GPIO stamps included.
set avs_refclk_family [get_clocks -quiet {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}]
set avs_periph_family [get_clocks -quiet {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}]
if { [sizeof_collection $avs_refclk_family] && [sizeof_collection $avs_periph_family] } {
    set_clock_groups -logically_exclusive -group $avs_refclk_family -group $avs_periph_family
}

# SPI.CLK is the SEP SPI host's SCK, a flop output toggled on SMUCLK, so it and the
# copy driven onto core2pad_o[9] belong to the SMUCLK domain. The copy returning on
# pad2core_i[9] crosses the pad and stays its own domain. Without SEP, spi_clk_i is
# tied off.
if { [sizeof_collection [get_cells -quiet gen_sep.u_sep]] > 0 } {
    create_generated_clock [get_pins u_smc/spi_clk_i] -name SPICLK -master_clock SMUCLK -divide_by 2 -source [get_ports "clk_smu_i"]
    create_generated_clock [get_ports {pad2core_i[9]}] -name SPICLK_IN_GPIO -master_clock SPICLK -divide_by 1 -source [get_pins u_smc/spi_clk_i]
    create_generated_clock [get_ports {core2pad_o[9]}] -name SPICLK_OUT_GPIO -master_clock SPICLK -divide_by 1 -source [get_pins u_smc/spi_clk_i]
    cdc_group_extra SMUCLK {SPICLK SPICLK_OUT_GPIO}
}

# External entropy sample clock. The SEP replay ran sep.resets.tcl before this clock
# existed, so its power-good sequence to the clock is declared here.
create_clock -add -name ENTROPY_ROSC_CLK -period $clock_periods(ENTROPY_ROSC_PERIOD) \
    [get_ports "entropy_rosc_sample_clk_i"]
set_rdc_define_assertion_sequence -from_reset POWERGOOD_STABLE_N -to_clock ENTROPY_ROSC_CLK

################################################################################
# GPIO core2pad OUTPUT IGNORE
################################################################################
# core2pad_o[*] outputs are constrained to ck_feedthru (async virtual clock).
# These are GPIO pad outputs driven from SMC register fields (SMUCLK here); the crossing
# to ck_feedthru is expected and does not require synchronization since the
# destination is a primary output going to pads with no clock relationship.
set_cdc_ignore_path \
    -to [get_ports {core2pad_o*}] \
    -type cdc_crossing \
    -comments "GPIO core2pad outputs: SMCCLK register to async pad, no sync needed"

# The pads also reconverge at the padring mux, where per-pad DATA_CTRL fields
# (interface_enable, lsio_select, lsio_disable) choose between the core2pad
# register and a protocol source. No in-block flop receives the result, so the
# glitch checks on every output stop at the port. The exported SPI clock
# (core2pad_o[9]) and AVS clock (core2pad_o[49]) keep the clock-path glitch
# check: a select change while one of those clocks runs glitches the clock the
# external device samples on.
set core2pad_clock_pads [get_ports {core2pad_o[9] core2pad_o[49]}]
set_cdc_ignore_path \
    -to [get_ports {core2pad_o*}] \
    -type glitch \
    -comments "GPIO core2pad: padring mux reconvergence at a terminal output with no in-block receiver."
set_cdc_ignore_path \
    -to [remove_from_collection [get_ports {core2pad_o*}] $core2pad_clock_pads] \
    -type clock_path_glitch \
    -comments "GPIO core2pad: padring mux reconvergence at a terminal output; the exported SPI and AVS clock pads stay checked."
