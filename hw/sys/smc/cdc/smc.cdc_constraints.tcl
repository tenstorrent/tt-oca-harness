# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# smc.cdc_constraints.tcl
#
# Instance-level SMC CDC declarations (UDS, convergence fan-in) that reference SMC
# hierarchy and do not belong to the DBM IP file smc.dfd_debug_bus_mux.tcl.
#
# Sourcing order in `cdc/smc.cdc_rdc.tcl`:
#   1. flows/cdc/cdc_rdc_setup.tcl, smc.cdc_rdc_setup.tcl  (methodology + bulk fan-in)
#   2. smc.dfd_debug_bus_mux.tcl   (DBM-only)
#   3. smc.cdc_constraints.tcl     (this file)
#
# Sections:
#   1. AVS sdata serial sample chain as a User Defined Synchronizer (UDS)
#   2. Independent fan-in convergence ignore
################################################################################

puts "INFO: Loading SMC-specific CDC constraints"

# Hierarchy-reusable: anchored instance paths go through cdc_inst; pad2core_i[51] keeps
# the same port name at the SMU top, so its get_ports reference needs no mapping.
if { [info procs cdc_conv_apply] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
}

################################################################################
# 1. AVS SDATA SERIAL SAMPLE CHAIN AS A USER-DEFINED SYNCHRONIZER
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

################################################################################
# 2. INDEPENDENT FAN-IN SIGNALS - CONVERGENCE IGNORE-AMONG
################################################################################
# Per-bit synchronized signals that later meet in a mux/OR/read-data cone but
# carry no cross-bit coherency requirement. Contributed to the single cumulative
# configure_cdc_convergence via cdc_conv_ignore_among (see hier_reuse_procs.tcl).
#
#   - ext_interrupts_i / ext_debug_bus_i: per-bit external level signals, each
#     synchronized independently in u_smc_base. Reconvergence in the DFD debug
#     bus mux and CPU CSR read data (PLIC pending / xbar D-channel)
#   - peripherals_cdc IRQ syncs (+ ndmreset per-core requests): independent
#     level interrupts ORed / vectored toward the CPU.
#   - SEP WDT IRQ resync (u_rst_ext_wdt_irq_sync at smc_peripherals top): independent
#     level interrupt into PLIC fan-in.
#   - GPIO pad2core syncs: independent pad inputs.
#   - DFD refclk-counter gray sync (u_ref_cnt_sync): gray-coded, single-bit
#     transition per source edge; safe to decode.
#   - tlDM AsyncQueue handshake syncs: independent req/ack channels of the
#     generated debug module. Reconvergence with interrupt bits in TileLink
#     read data with no coherency requirement.
#   - avsbus controller status/gray syncs: independent event flags and FIFO
#     gray pointers ORed into interrupt_o / interrupt CSR next-state logic.
#   - i3c SCL/SDA pad syncs: the two wires of one open-drain bus, synchronized
#     separately by the vendor xphy; the I3C protocol itself tolerates their
#     relative skew (SDA transitions are qualified by SCL state by design).
#   - DBM observation-only syncs (i2c debug, reset-complete, cool-reset-wrap
#     handshake, boot-stall): independent single-bit status lanes read through the
#     debug bus mux and PeakRDL readback OR-trees, one lane selected at a time.

proc _smc_conv_ignore { label pattern } {
    set p [get_pins -quiet [cdc_inst $pattern]]
    if { [sizeof_collection $p] > 0 } {
        cdc_conv_ignore_among $p
        puts "INFO: conv-ignore-among: $label => [sizeof_collection $p] pins"
    } else {
        puts "WARNING: conv-ignore-among: no pins match '$label' ([cdc_inst $pattern]) - skipped"
    }
}

# cdc_conv_ignore_among combines all pins across all calls into a single group to ignore convergence
# all signals across these calls have no coherency requirement
_smc_conv_ignore ext_interrupts {u_smc_base/u_ext_interrupts_sync3/*/q_ddd/Q}
_smc_conv_ignore ext_debug_bus {u_smc_base/u_ext_debug_bus_sync3/*/q_ddd/Q}
_smc_conv_ignore i3c_irq {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_i3c_irq_sync/*/q_ddd/Q}
_smc_conv_ignore uart_irq {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_uart_combined_irq_sync/*/q_ddd/Q}
_smc_conv_ignore i2c_irq {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_i2c_irq_sync/*/q_ddd/Q}
_smc_conv_ignore avsbus_irq {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_avsbus_irq_sync/*/q_ddd/Q}
_smc_conv_ignore ndmreset_req {u_smc_peripherals/u_smc_peripherals_cdc/u_ndmreset_request_sync/*/q_ddd/Q}
_smc_conv_ignore sep_wdt_irq {u_smc_peripherals/u_rst_ext_wdt_irq_sync/*/q_ddd/Q}
_smc_conv_ignore gpio_pad2core {u_smc_peripherals/u_smc_padring/*/u_pad2core_sync/*/q_ddd/Q}
_smc_conv_ignore dfd_refcnt_gray {u_smc_base/u_internal_regs/u_smc_dfd_wrap/u_ref_cnt_sync/*/q_ddd/Q}
_smc_conv_ignore avs_unresponsive {u_smc_peripherals/u_avsbus_controller/u_slave_unresponsive_resync/*/q_ddd/Q}
_smc_conv_ignore avs_slave_int {u_smc_peripherals/u_avsbus_controller/u_slave_interrupt_resync/*/q_ddd/Q}
_smc_conv_ignore avs_max_retries {u_smc_peripherals/u_avsbus_controller/u_max_retries_attempted_resync/*/q_ddd/Q}
_smc_conv_ignore avs_readback_en {u_smc_peripherals/u_avsbus_controller/u_avs_readback_en_resync/*/q_ddd/Q}
_smc_conv_ignore avs_rb_fifo_full {u_smc_peripherals/u_avsbus_controller/u_readback_fifo_full_resync/*/q_ddd/Q}
_smc_conv_ignore avs_cmd_gray {u_smc_peripherals/u_avsbus_controller/u_cmd_async_fifo_inst/*/*/q_ddd/Q}
_smc_conv_ignore avs_rb_gray {u_smc_peripherals/u_avsbus_controller/u_readasync_back_fifo_inst/*/*/q_ddd/Q}
_smc_conv_ignore avs_resync_pend {u_smc_peripherals/u_avsbus_controller/u_slave_resync_pending_resync/*/q_ddd/Q}
_smc_conv_ignore i2c_debug {u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_i2c_debug_sync/*/q_ddd/Q}
_smc_conv_ignore boot_stall {u_smc_peripherals/u_boot_stall_combined_sync/*/q_ddd/Q}
_smc_conv_ignore reset_complete {u_smc_peripherals/u_smc_reset_unit/u_smc_subsystem_resets/u_reset_complete_sync/*/q_ddd/Q}
_smc_conv_ignore cool_isolate_req {u_smc_peripherals/u_smc_reset_unit/u_smc_cool_reset_wrap/u_isolate_req_pin_sync/*/q_ddd/Q}
_smc_conv_ignore cool_flr_smc {u_smc_peripherals/u_smc_reset_unit/u_smc_cool_reset_wrap/u_cfg_flr_pf_active_sync_smc/*/q_ddd/Q}
_smc_conv_ignore cool_flr_ref {u_smc_peripherals/u_smc_reset_unit/u_smc_cool_reset_wrap/u_cfg_flr_pf_active_sync_ref/*/q_ddd/Q}
_smc_conv_ignore cool_rst_ni {u_smc_peripherals/u_smc_reset_unit/u_smc_cool_reset_wrap/u_rst_cool_ni_sync_smc/*/q_ddd/Q}
_smc_conv_ignore cool_rst_no {u_smc_peripherals/u_smc_reset_unit/u_smc_cool_reset_wrap/u_rst_cool_no_sync_smc/*/q_ddd/Q}
_smc_conv_ignore i3c_scl_pad {u_smc_peripherals/u_i3ccore_wrapper/*/u_i3c/xphy/scl_synchronizer/u_sync_2/q_o/Q*}
_smc_conv_ignore i3c_sda_pad {u_smc_peripherals/u_i3ccore_wrapper/*/u_i3c/xphy/sda_synchronizer/u_sync_2/q_o/Q*}

rename _smc_conv_ignore {}

# tlDM AsyncQueue handshake sync outputs: instance names are generate-produced
# with no bracket-free glob, so collect the sync cells by ref and take each
# cell's wrapped-flop Q.
set _tldm_sync_cells [get_cells -hier -filter {full_name =~ *tlDM*prim_flop_3sync_r} -quiet]
set _tldm_sync_pins [list]
foreach_in_collection c $_tldm_sync_cells {
    set p [get_pins -quiet "[get_object_name $c]/q_ddd/Q"]
    if {[sizeof_collection $p] > 0} { lappend _tldm_sync_pins {*}[get_object_name $p] }
}
if { [llength $_tldm_sync_pins] > 0 } {
    cdc_conv_ignore_among $_tldm_sync_pins
    puts "INFO: conv-ignore-among: tlDM handshake syncs => [llength $_tldm_sync_pins] pins"
} else {
    puts "WARNING: conv-ignore-among: no tlDM prim_flop_3sync_r sync pins found - skipped"
}

puts "INFO: SMC-specific CDC constraints loaded."
