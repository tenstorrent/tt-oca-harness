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

# SPI.CLK on the GPIO pads.
create_generated_clock [get_ports {pad2core_i[9]}] -name SPICLK_IN_GPIO -master_clock SPICLK -divide_by 1 -source [get_pins u_smc/spi_clk_i]
create_generated_clock [get_ports {core2pad_o[9]}] -name SPICLK_OUT_GPIO -master_clock SPICLK -divide_by 1 -source [get_pins u_smc/spi_clk_i]

# External entropy sample clock. The SEP replay ran sep.resets.tcl before this clock
# existed, so its power-good sequence to the clock is declared here.
create_clock -add -name ENTROPY_ROSC_CLK -period $clock_periods(ENTROPY_ROSC_PERIOD) \
    [get_ports "entropy_rosc_sample_clk_i"]
set_rdc_define_assertion_sequence -from_reset POWERGOOD_STABLE_N -to_clock ENTROPY_ROSC_CLK

################################################################################
# GPIO PAD-ENABLE OUTPUT IGNORE
################################################################################
# core2pad_en_o[*] and pad2core_en_o[*] drive the pad cells' output and input
# enables: primary outputs with no receiving flop, like core2pad_o[*]. Only the
# crossing check is dropped. They carry live protocol output enables (I2C, I3C,
# SPI), so glitch analysis stays.
set_cdc_ignore_path \
    -to [get_ports {core2pad_en_o* pad2core_en_o*}] \
    -type cdc_crossing \
    -comments "GPIO pad enables: register or protocol enable to async pad, no sync needed"

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

# Separate from the generic async-crossing ignore above: pad outputs are also
# structurally reconvergent at the padring mux (per-pad DATA_CTRL fields such as
# interface_enable, lsio_select, lsio_disable, core2pad vs protocol sources —
# SPI clock, AVS clock, UART TX, etc.). There is no in-block receiving flop past
# the primary output. Static CDC may still run glitch-stage checks on that
# terminal reconvergence; we scope glitch suppression to the port without
# dropping ordinary crossing analysis (the separate `-type cdc_crossing` ignore
# stays in place). Broadening the ignore to wipe all crossing-class checks on
# these ports would hide real unsynchronized-path issues—avoid that.
#
# User-path glitch APIs (`set_user_ignore_path`, `configure_userpath_glitch`)
# target a different optional analysis family than CDC-path glitch suppression;
# product documentation distinguishes them. Use `set_cdc_ignore_path` with
# `-type` glitch / clock_path_glitch for pad-drive glitch noise on outputs.
#
# Keep `-type {glitch clock_path_glitch}` additive to `-type cdc_crossing`.
# Include clock_path_glitch so bits that behave as exported clocks under muxing
# remain covered if the tool classifies them that way in a future rev.
set_cdc_ignore_path \
    -to [get_ports {core2pad_o*}] \
    -type {glitch clock_path_glitch} \
    -comments "GPIO core2pad: limit glitch-stage checks on terminal outputs; padring mux reconvergence is intentional. Ordinary CDC crossing handling stays via the separate cdc_crossing ignore."

################################################################################
# AVS SDATA SERIAL SAMPLE CHAIN AS A USER-DEFINED SYNCHRONIZER (CDC only)
################################################################################
# `avs_sdata_capture` (32-bit) and `avs_sdata_interrupt_detect` (2-bit) are
# both shift registers clocked on `negedge avs_clk` that shift in the
# asynchronous `avs_sdata_i` input (= `pad2core_i[51]`). The first stage of
# each chain IS the metastability-resolving flop, and downstream stages
# provide additional settling time. Functionally these are user-defined
# multi-flop synchronizers, but VC SpyGlass cannot infer this on its own
# because the shift registers also do useful work (frame capture / 2-of-2
# interrupt qualification).
#
# Declare both chains as data synchronizers so the tool stops reporting
# `NO_SYNC_METHOD` on the input flop. The AVS protocol guarantees the slave
# drives `sdata` synchronously to its received `avs_clk` edges, so the actual
# CDC risk is bounded to occasional metastability events that the multi-stage
# shift register absorbs.

# NOTE on syntax:
#   `configure_cdc_data_sync` requires `-from_obj` / `-to_obj` (and
#   `-from_clock` / `-to_clock`) — bare `-from` / `-to` are ambiguous
#   in VC SpyGlass CDC and trigger CMD-011 / CMD-012 at read-in, which
#   silently drops the UDS declaration and resurfaces the underlying
#   CDC_UNSYNC_NOSCHEME.
#
# NOTE on target pin:
#   VC SpyGlass anchors data-sync declarations at the Q output of the
#   first-stage flop (the synchronizer output), not the D input. Passing
#   D* pins triggers `TCL_COMMAND_INVALID ... Design Objects are not valid
#   destination(s) of any crossing` and the declaration is ignored.
#   We therefore target `.../Q[0]` — the LSB of each shift register is
#   the one that directly captures `avs_sdata_i` (= `pad2core_i[51]`);
#   higher bits are tap-delay stages that move previously captured data.
#
# NOTE on -sync_check_type value:
#   The valid keyword is `enable_with_des_domain` (NOT `enable_with_dest_domain`
#   — note the missing 't' in "des"). VC SpyGlass rejects the longer spelling
#   with `CMD-031: value 'enable_with_dest_domain' for option '-sync_check_type'
#   is not valid. Specify one of: enable_with_des_domain, enable_with_qual,
#   qual_only`. The error is non-fatal — the surrounding `if` block continues
#   executing — but the `configure_cdc_data_sync` call itself is dropped, so
#   no UDS gets declared and `NO_SYNC_METHOD` reappears on the first-stage
#   flop. (We carry this typo-warning here because the spelling is
#   counter-intuitive and the failure mode is silent at the report level.)
#
# NOTE on sync_check_type semantics:
#   Both shift-register first stages are enabled flops — synthesis infers
#   the enable from the `cur_state != ...` / `cur_state == ...` guard in
#   the `always_ff` block. `cur_state` lives on `negedge avs_clk`, so the
#   enable is a valid destination-domain qualifier. VC SpyGlass cannot
#   prove this on its own because `cur_state` transitions depend on CSRs
#   that cross from the SMC system clock; it emits `NO_SYNC_METHOD: Enable Criteria not
#   satisfied, no valid qualifier`. `-sync_check_type enable_with_des_domain`
#   tells the tool "accept the native flop enable as the qualifier as long
#   as it's in the destination domain", which is the correct semantic for
#   this design.

# avs_sdata_capture[31:0] - protocol frame shift register
if { $::cdc_app eq "cdc" } {
    set avs_sdata_capture_q0_pin \
        [get_pins -quiet {u_smc/u_smc_peripherals/u_avsbus_controller/avs_sdata_capture/Q[0]}]
    if { [sizeof_collection $avs_sdata_capture_q0_pin] > 0 } {
        configure_cdc_data_sync \
            -from_obj [get_ports {pad2core_i[51]}] \
            -to_obj $avs_sdata_capture_q0_pin \
            -sync_check_type enable_with_des_domain
        puts "INFO: Declared avs_sdata_capture/Q\[0\] as UDS for pad2core_i\[51\] (enable_with_des_domain)"
    } else {
        puts "WARNING: Found no avs_sdata_capture/Q\[0\] pin -- UDS for AVS sdata capture not applied"
    }

    # avs_sdata_interrupt_detect[1:0] - 2-stage qualifier for slave-issued interrupts
    set avs_sdata_intdet_q0_pin \
        [get_pins -quiet {u_smc/u_smc_peripherals/u_avsbus_controller/avs_sdata_interrupt_detect/Q[0]}]
    if { [sizeof_collection $avs_sdata_intdet_q0_pin] > 0 } {
        configure_cdc_data_sync \
            -from_obj [get_ports {pad2core_i[51]}] \
            -to_obj $avs_sdata_intdet_q0_pin \
            -sync_check_type enable_with_des_domain
        puts "INFO: Declared avs_sdata_interrupt_detect/Q\[0\] as UDS for pad2core_i\[51\] (enable_with_des_domain)"
    } else {
        puts "WARNING: Found no avs_sdata_interrupt_detect/Q\[0\] pin -- UDS for AVS sdata interrupt detect not applied"
    }
}
