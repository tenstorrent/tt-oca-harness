# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# smc_cdc_rdc_setup.tcl - SMC-specific CDC/RDC instance constraints
#
# Block-specific, instance-level annotation for the SMC block in OCAH.
# Shared type-level setup (synchronizer / IP / convergence config and the
# collect_prim_flop_3sync_qpins helper) lives in
# `flows/cdc/cdc_rdc_setup.tcl`, sourced first.
# Sourced by both vccdc and vcrdc flows (see
# `cdc/smc.cdc_rdc.tcl`).
#
# Companion files (vccdc only):
#   - cdc_constraints_dfd_debug_bus_mux.tcl  (DBM IP-scoped)
#   - cdc_constraints_smc.tcl                (SMC instance-level UDS)
#   - dfd_top_cdc_waivers.tcl                (DFD IP waivers)
################################################################################

puts "INFO: Loading SMC-specific CDC/RDC constraints"

# GPIO padring control intent:
# - The top-level AXI-Lite GPIO control bus is intended to be an `SMCCLK`
#   control plane.
# - Adopter-specific logic inside `smc_padring_ext` must add any local CDC
#   explicitly rather than relying on the top-level GPIO control bus to be a
#   `REFCLK` bus.
# - The per-GPIO pad configuration fields sourced from `gpio_ctrl_reg`
#   (`drive_strength`, `pull_enable_n0_scan`, `pull_select`,
#   `schmitt_select`, `config_enable`, `hw2_ovrd`) are intentionally left
#   without a blanket CDC exception here until their custom solution is
#   defined.

################################################################################
# GLITCH-FREE CELL CONFIGURATION
################################################################################

configure_glitch_free_cells -ignore_modules {prim_ag_clk_mux}

# prim_ag_clk_mux (e.g. avsbus_controller u_refclk_apbclk_mux): inner flops can sit under
# different clock roots until exclusive clock modeling is complete in hw/sys/smc/synth/smc_clocks.sdc.
# define_glitch_free_mux + configure_glitch_free_cells declare the mux glitch-safe per
# methodology; treat residual inner-cell flop crossings as structural/library-contained
# analysis, not pad-boundary CDC.

define_glitch_free_mux -module prim_ag_clk_mux \
    -clock {clk0_i clk1_i} \
    -select {sel_i}

################################################################################
# ASYNC-RESET SYNCHRONIZERS (SMC CPU CLUSTER)
################################################################################
# SMC-CPU-complex (Chipyard/Rocket) async-reset synchronizer modules.
configure_cdc_asyncrst_nff_sync -uds_modules {
    OCAH4CORECluster_AsyncResetSynchronizerPrimitiveShiftReg_d3_i0
    OCAH4CORECluster_AsyncResetSynchronizerShiftReg_w1_d3_i0
    OCAH4CORECluster_ResetCatchAndSync_d3
}

################################################################################
# GRAY SIGNAL CONFIGURATION
################################################################################

### cdc_fifo_gray boundary pointers
# cdc_fifo_gray is IP-blocked, but async_wptr/async_rptr are visible at the
# parent boundary (axi_cdc, apb_cdc). Annotate as gray for convergence.
# Use async_wptr* and async_rptr* specifically — NOT async* which would
# incorrectly mark the raw data bus (async_data) as gray-coded.

set cdc_fifo_wptr [get_pins -hier *cdc_fifo_gray*/async_wptr* -quiet]
set cdc_fifo_rptr [get_pins -hier *cdc_fifo_gray*/async_rptr* -quiet]

if { [sizeof_collection $cdc_fifo_wptr] > 0 } {
    set_gray_signals -gray_signals $cdc_fifo_wptr
    cdc_conv_ignore_among $cdc_fifo_wptr
    puts "INFO: Annotated [sizeof_collection $cdc_fifo_wptr] cdc_fifo_gray async_wptr as gray"
}
if { [sizeof_collection $cdc_fifo_rptr] > 0 } {
    set_gray_signals -gray_signals $cdc_fifo_rptr
    cdc_conv_ignore_among $cdc_fifo_rptr
    puts "INFO: Annotated [sizeof_collection $cdc_fifo_rptr] cdc_fifo_gray async_rptr as gray"
}

### AVS gray signals (prim_sync3 output is q_o, not the input signal name)
set gray_avs_signals [get_pins -hier *_ptr_gray_sync_to_*_clk*/q_o -quiet]
if { [sizeof_collection $gray_avs_signals] > 0 } {
    set_gray_signals -gray_signals $gray_avs_signals
    cdc_conv_ignore_among $gray_avs_signals
    puts "INFO: Configured [sizeof_collection $gray_avs_signals] AVS gray signals"
}

################################################################################
# avsbus_async_fifo SURGICAL CDC CONSTRAINTS
################################################################################
# avsbus_async_fifo is architecturally identical to tt_async_fifo:
# dual-clock FIFO with gray-coded pointers synchronized via prim_sync3
# (3-stage FF chain). NOT marked as IP block so SpyGlass can verify the
# synchronizer chains. Storage array crossing and pointer convergence
# need targeted constraints to suppress false violations.
#
# Architecture (from avsbus_async_fifo.sv):
#   - fifo_array[DEPTH]: written by i_wr_clk, read combinatorially by i_rd_clk
#   - wr_ptr_gray → wr_ptr_gray_sync_to_rd_clk (prim_sync3) → wr_ptr_gray_rd_clk
#   - rd_ptr_gray → rd_ptr_gray_sync_to_wr_clk (prim_sync3) → rd_ptr_gray_wr_clk
#   - Read pointer advances only after synced write pointer confirms data
#     stability (>=3 sync stage latency).
#
# Instances in avsbus_controller:
#   - cmd_async_fifo_inst    (clk_reg_i → avs_clk)
#   - readasync_back_fifo_inst (avs_clk → clk_reg_i)

set avs_fifo_cells [get_cells -hier -filter "ref_name =~ avsbus_async_fifo*" -quiet]

if { [sizeof_collection $avs_fifo_cells] > 0 } {
    set avs_fifo_conv_signals [list]

    foreach cell_hier [get_object_name $avs_fifo_cells] {
        # Storage array: ignore cross-domain path from fifo_array Q pins.
        #     Gray-coded pointer sync guarantees data is stable before the
        #     read pointer reaches it.
        set storage_pins [get_pins "$cell_hier/fifo_array*/Q" -quiet]
        if { [sizeof_collection $storage_pins] > 0 } {
            set_cdc_ignore_path -from $storage_pins
        }

        # Gray pointer registers: annotate source gray-coded pointer FFs.
        set wr_gray_reg [get_pins "$cell_hier/wr_ptr_gray*/Q" -quiet]
        set rd_gray_reg [get_pins "$cell_hier/rd_ptr_gray*/Q" -quiet]
        if { [sizeof_collection $wr_gray_reg] > 0 } {
            set_gray_signals -gray_signals $wr_gray_reg
            cdc_conv_ignore_among $wr_gray_reg
        }
        if { [sizeof_collection $rd_gray_reg] > 0 } {
            set_gray_signals -gray_signals $rd_gray_reg
            cdc_conv_ignore_among $rd_gray_reg
        }

        # Synced gray pointers: annotate synchronized outputs as gray
        #     to prevent false convergence at gray-to-binary decoder.
        set wptr_sync_pins [get_pins "$cell_hier/u_wr_ptr_gray_sync_to_rd_clk*/q_o" -quiet]
        set rptr_sync_pins [get_pins "$cell_hier/u_rd_ptr_gray_sync_to_wr_clk*/q_o" -quiet]
        if { [sizeof_collection $wptr_sync_pins] > 0 } {
            set_gray_signals -gray_signals $wptr_sync_pins
            cdc_conv_ignore_among $wptr_sync_pins
            foreach p [get_object_name $wptr_sync_pins] { lappend avs_fifo_conv_signals $p }
        }
        if { [sizeof_collection $rptr_sync_pins] > 0 } {
            set_gray_signals -gray_signals $rptr_sync_pins
            cdc_conv_ignore_among $rptr_sync_pins
            foreach p [get_object_name $rptr_sync_pins] { lappend avs_fifo_conv_signals $p }
        }

        # Output data: rd_data_o bits share a single read pointer address.
        #     Not independently asynchronous — no coherency concern.
        set rd_data_pins [get_pins "$cell_hier/rd_data_o" -quiet]
        if { [sizeof_collection $rd_data_pins] > 0 } {
            cdc_conv_ignore_among $rd_data_pins
        }
    }

    # Cross-instance convergence ignore for all synced gray pointers.
    if { [llength $avs_fifo_conv_signals] > 0 } {
        set_gray_signals -gray_signals $avs_fifo_conv_signals
        cdc_conv_ignore_among $avs_fifo_conv_signals
    }

    puts "INFO: Configured [sizeof_collection $avs_fifo_cells] avsbus_async_fifo instances"
} else {
    puts "INFO: No avsbus_async_fifo instances found (skipping)"
}

################################################################################
# prim_fifo_async SURGICAL CDC CONSTRAINTS
################################################################################
# prim_fifo_async (vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl/prim_fifo_async.sv, TT delta applied via
# vendor/lowRISC/opentitan/patches/prim_fifo_async_ptrdiff.patch) is the OpenTitan-style
# dual-clock FIFO with gray-coded pointer synchronization. Architecturally
# equivalent to avsbus_async_fifo above, but uses prim_flop_2sync (already
# UDS-listed in flows/cdc/cdc_rdc_setup.tcl) for pointer sync and exposes pointer/storage
# nets with slightly different names.
#
# RTL signals (per instance) we constrain:
#   - fifo_wptr_gray_q / fifo_rptr_gray_q : source-side gray pointer flops
#   - sync_wptr/gen_sync[N].d0nt_wrap_sync / sync_rptr/gen_sync[N].d0nt_wrap_sync
#       : synced gray pointer outputs (prim_flop_2sync, one cell per bit)
#   - fifo_wptr_sync_combi / fifo_rptr_sync_combi
#       : combinational gray2bin/identity decode of the synced gray pointer
#         (a common combinational convergence point in static CDC)
#   - storage[Depth] : data array, written on wclk, read combinationally on rclk
#
# Instances include:
#   - u_smc_peripherals/u_telemetry_receiver_wrap/gen_telemetry_receivers[0..2]/
#         u_at_req_fifo_async       (TELEMETRYCLK <-> SMCCLK, depth 8, 4 pointer bits)
# Keeping the surgical pattern (rather than configure_ip_block) preserves
# visibility into prim_flop_2sync chains for verification.
#
# The refclk counter's cnt_update_async_fifo (inside prim_refclk_count_w_cdc)
# is constrained in flows/cdc/cdc_rdc_setup.tcl and skipped here.

# Synced gray pointer output stage (u_sync_2/q_o) of a prim_fifo_async
# sync_wptr/sync_rptr prim_flop_2sync, one bit per pointer bit.
proc smc_prim_fifo_sync_ptr_pins { cell_hier ptr_inst } {
    set pins [get_pins "$cell_hier/$ptr_inst/u_sync_2/q_o/Q*" -quiet]
    if { [sizeof_collection $pins] == 0 } {
        puts "WARNING: prim_fifo_async ($cell_hier): no $ptr_inst/u_sync_2/q_o pins found - pointer sync stage left unconstrained"
        return ""
    }
    puts "INFO: prim_fifo_async ($cell_hier): $ptr_inst has [sizeof_collection $pins] pointer bits"
    return $pins
}

# Try wildcard ref_name match first (handles parameterized elaborated names);
# fall back to instance-name pattern for the known instantiation
# (telemetry at_req_fifo_async).
set prim_fifo_async_cells [get_cells -hier -filter "ref_name =~ prim_fifo_async*" -quiet]
if { [sizeof_collection $prim_fifo_async_cells] == 0 } {
    set prim_fifo_async_cells [get_cells -hier *u_at_req_fifo_async -quiet]
}

if { [sizeof_collection $prim_fifo_async_cells] > 0 } {
    set prim_fifo_conv_signals [list]

    foreach cell_hier [get_object_name $prim_fifo_async_cells] {
        # cnt_update_async_fifo is constrained in flows/cdc/cdc_rdc_setup.tcl.
        if { [string match *u_cnt_update_async_fifo $cell_hier] } { continue }

        # Storage array: ignore cross-domain path from storage Q pins.
        #     Gray-coded pointer sync guarantees data is stable before the
        #     read pointer reaches the corresponding entry.
        set storage_pins [get_pins "$cell_hier/storage*/Q" -quiet]
        if { [sizeof_collection $storage_pins] > 0 } {
            set_cdc_ignore_path -from $storage_pins
        }

        # Source-side gray pointer flops.
        set wr_gray_reg [get_pins "$cell_hier/fifo_wptr_gray_q*/Q" -quiet]
        set rd_gray_reg [get_pins "$cell_hier/fifo_rptr_gray_q*/Q" -quiet]
        if { [sizeof_collection $wr_gray_reg] > 0 } {
            set_gray_signals -gray_signals $wr_gray_reg
            cdc_conv_ignore_among $wr_gray_reg
        }
        if { [sizeof_collection $rd_gray_reg] > 0 } {
            set_gray_signals -gray_signals $rd_gray_reg
            cdc_conv_ignore_among $rd_gray_reg
        }

        # Synced gray pointer outputs (prim_flop_2sync output stage):
        #     sync_wptr/gen_sync[N].d0nt_wrap_sync/Q, one per pointer bit
        #     (PTR_WIDTH = clog2(Depth)+1). See smc_prim_fifo_sync_ptr_pins.
        set wptr_sync_pins [smc_prim_fifo_sync_ptr_pins $cell_hier sync_wptr]
        set rptr_sync_pins [smc_prim_fifo_sync_ptr_pins $cell_hier sync_rptr]
        if { [sizeof_collection $wptr_sync_pins] > 0 } {
            set_gray_signals -gray_signals $wptr_sync_pins
            cdc_conv_ignore_among $wptr_sync_pins
            foreach p [get_object_name $wptr_sync_pins] { lappend prim_fifo_conv_signals $p }
        }
        if { [sizeof_collection $rptr_sync_pins] > 0 } {
            set_gray_signals -gray_signals $rptr_sync_pins
            cdc_conv_ignore_among $rptr_sync_pins
            foreach p [get_object_name $rptr_sync_pins] { lappend prim_fifo_conv_signals $p }
        }

        # Read data output: rdata_o bits share a single read pointer.
        set rd_data_pins [get_pins "$cell_hier/rdata_o" -quiet]
        if { [sizeof_collection $rd_data_pins] > 0 } {
            cdc_conv_ignore_among $rd_data_pins
        }
    }

    # Cross-instance convergence ignore for synced gray pointers
    # collected across all prim_fifo_async instances.
    if { [llength $prim_fifo_conv_signals] > 0 } {
        set_gray_signals -gray_signals $prim_fifo_conv_signals
        cdc_conv_ignore_among $prim_fifo_conv_signals
    }

    puts "INFO: Configured [sizeof_collection $prim_fifo_async_cells] prim_fifo_async instances"
} else {
    puts "INFO: No prim_fifo_async instances found (skipping)"
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
# INDEPENDENT FAN-IN CONVERGENCE-IGNORE
################################################################################
# The DBM observation lanes and the PeakRDL readback OR-trees combine independently
# synchronized single-bit sources with no cross-bit coherency requirement. Their
# per-bit synchronizer outputs are contributed in cdc_constraints_smc.tcl section 2;
# the prim_fifo_async gray-pointer syncs above and the cnt_update_async_fifo syncs in
# flows/cdc/cdc_rdc_setup.tcl join the same cumulative cdc_conv_ignore_among union.

################################################################################
# PLIC / TileLink READBACK FAN-IN CONVERGENCE IGNORE-AT POINTS
################################################################################
# At the CPU PLIC register, all independently synchronized interrupt bits reconverge
# there by construction, with no multi-bit coherency requirement (see
# cdc_constraints_smc.tcl section 2). Suppress convergence AT that readback bus
set _plic_readback_nets [get_nets -quiet [cdc_inst {u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/cbus/out_xbar/auto_anon_in_d_bits_data*}]]
if { [sizeof_collection $_plic_readback_nets] > 0 } {
    cdc_conv_ignore_at [get_object_name $_plic_readback_nets]
    puts "INFO: Contributed [sizeof_collection $_plic_readback_nets] cbus/out_xbar readback nets as convergence ignore-at points"
} else {
    puts "WARNING: no cbus/out_xbar auto_anon_in_d_bits_data nets found - PLIC readback ignore-at skipped"
}
unset -nocomplain _plic_readback_nets

# Further intentional fan-in convergence points (same rationale as above):
#   - plic/fanin/* and gateways_gateway_*/inFlight: the PLIC's OR/priority tree
#     over independent IRQ lanes (rocket-chip generated).
#   - u_ref_cnt_gray2bin/z_o*: gray-decode of the synced refclk counter (single-bit
#     transition per source edge; see the global prim_gray2bin annotation).
#   - avsbus interrupt_o / AVS_INTERRUPT readback-overflow next-state: OR of
#     independent event flags into a level interrupt / its CSR mirror.
#   - peripheral_interrupts_o: vector of independent per-source interrupts.
proc _smc_conv_at { label kind pattern } {
    if { $kind eq "net" } {
        set objs [get_nets -quiet [cdc_inst $pattern]]
    } else {
        set objs [get_pins -quiet [cdc_inst $pattern]]
    }
    if { [sizeof_collection $objs] > 0 } {
        cdc_conv_ignore_at [get_object_name $objs]
        puts "INFO: conv-ignore-at: $label => [sizeof_collection $objs] ${kind}s"
    } else {
        puts "WARNING: conv-ignore-at: no ${kind}s match '$label' ([cdc_inst $pattern]) - skipped"
    }
}
set _plic_hier {u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/plic_domain/plic}
_smc_conv_at plic_fanin_nets net "${_plic_hier}/fanin*/*"
_smc_conv_at plic_gateway_inflight pin "${_plic_hier}/*/inFlight/D"
_smc_conv_at plic_pending_capture pin "${_plic_hier}/pending_*/D"
_smc_conv_at dfd_gray2bin_out pin {u_smc_base/u_internal_regs/u_smc_dfd_wrap/u_ref_cnt_gray2bin/z_o*}
_smc_conv_at avs_interrupt_o net {u_smc_peripherals/u_avsbus_controller/interrupt_o}
_smc_conv_at avs_rb_ovfl_next pin {u_smc_peripherals/u_avsbus_controller/R_avs_interrupt_F_readback_overflow_int/D*}
_smc_conv_at periph_interrupts net {u_smc_peripherals/peripheral_interrupts_o*}
rename _smc_conv_at {}
unset -nocomplain _plic_hier

puts "INFO: SMC-specific CDC/RDC constraints loaded."
