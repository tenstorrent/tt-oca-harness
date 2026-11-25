# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# smc.pad_boundary.tcl - SMC pad-boundary CDC constraints
#
# CDC annotations on SMC's pad ports: the core2pad_o output ignore paths and the
# AVS sdata synchronizer on the pad2core_i[51] input. Each models core2pad_o and
# pad2core_i as the chip boundary, which holds only where they are top ports. A
# parent whose pads sit between its ports and SMC (a padring, a bidirectional pad
# that feeds core2pad_o back into pad2core_i) constrains that boundary itself, so
# these apply at block top only. SMU states the same boundary for its own ports
# in hw/sys/smu/cdc/smu.pad_boundary.tcl.
################################################################################

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
}

if { ![cdc_is_block_top] } {
    puts "INFO: smc.pad_boundary: skipped under prefix '$::cdc_hier_prefix'; the parent\
          constrains the pad boundary"
    return
}

################################################################################
# GPIO core2pad OUTPUT IGNORE
################################################################################
# core2pad_o[*] outputs are constrained to ck_feedthru (async virtual clock).
# These are GPIO pad outputs driven from SMCCLK register fields; the crossing
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
#   that cross from SMCCLK; it emits `NO_SYNC_METHOD: Enable Criteria not
#   satisfied, no valid qualifier`. `-sync_check_type enable_with_des_domain`
#   tells the tool "accept the native flop enable as the qualifier as long
#   as it's in the destination domain", which is the correct semantic for
#   this design.

# avs_sdata_capture[31:0] - protocol frame shift register
if { $::cdc_app eq "cdc" } {
    set avs_sdata_capture_q0_pin \
        [get_pins -quiet [cdc_inst {u_smc_peripherals/u_avsbus_controller/avs_sdata_capture/Q[0]}]]
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
        [get_pins -quiet [cdc_inst {u_smc_peripherals/u_avsbus_controller/avs_sdata_interrupt_detect/Q[0]}]]
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
