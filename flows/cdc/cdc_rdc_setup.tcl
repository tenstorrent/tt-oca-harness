# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
################################################################################
# cdc_rdc_setup.tcl - shared CDC/RDC setup for every block
#
# Type-level synchronizer / IP / convergence configuration common to all blocks
# (smc, sep, dtp, smu). Each block's cdc/<block>.cdc_rdc.tcl sources it before
# the block's own instance-level annotation. It applies once per session: a
# parent that replays several child entries gets a single copy.
################################################################################

if { [info exists ::cdc_rdc_setup_done] } {
    puts "INFO: shared CDC/RDC setup already loaded - skipped"
    return
}
set ::cdc_rdc_setup_done 1

puts "INFO: Loading shared CDC/RDC setup"

if { [info procs cdc_conv_ignore_among] eq "" } {
    if { [info script] ne "" } {
        source [file normalize [file join [file dirname [info script]] \
            ../synth/constraints/hier_reuse_procs.tcl]]
    } elseif { [info exists ::env(GIT_ROOT)] } {
        source $::env(GIT_ROOT)/flows/synth/constraints/hier_reuse_procs.tcl
    } else {
        error "cdc_rdc_setup.tcl: cannot locate hier_reuse_procs.tcl; set GIT_ROOT"
    }
}

################################################################################
# GLITCH-FREE CELL CONFIGURATION
################################################################################
# prim_rst_mux2_hf_n: DFT reset bypass mux — override value is stable
# before mux select changes. Blocks append their own modules additively.
configure_glitch_free_cells -ignore_modules [cdc_mod {prim_rst_mux2_hf_n}]

################################################################################
# SYNCHRONIZER (NFF) CONFIGURATION
################################################################################
# IMPORTANT: Only list actual multi-flop synchronizer LEAF cells here.
# Do NOT include complex CDC modules (pulse syncs, handshakes, FIFOs,
# reset sequencers) — those have internal logic beyond simple FF chains
# and SpyGlass must analyze their internals.

configure_cdc_nff_sync -uds_modules [concat \
    [cdc_mod {prim_sync_reset prim_flop_3sync}] \
    {prim_sync2 prim_sync2r} \
    [cdc_mod {prim_sync3 prim_sync3r prim_sync4 prim_sync4r}] \
    [cdc_mod {prim_flop_2sync* prim_flop_3sync* prim_flop_4sync*}]]

# Async reset synchronizers: these specifically synchronize reset deassertion.
# Blocks append their own async-reset sync modules additively.
configure_cdc_asyncrst_nff_sync -uds_modules [cdc_mod {prim_sync_reset}]

# RDC synchronizer declaration: set_rdc_synchronizer tells the RDC engine
# that these modules are synchronizers, so RDC crossings with destinations
# inside them are considered blocked. Without this, the tool traces through
# their internal flops and reports false SETUP_RESET_ASSERT_MISSING errors.
set_rdc_synchronizer -sync_cell [concat \
    [cdc_mod {prim_sync_reset prim_flop_3sync}] \
    {prim_sync2 prim_sync2r} \
    [cdc_mod {prim_sync3 prim_sync3r prim_sync4 prim_sync4r}] \
    [cdc_mod {prim_flop_2sync* prim_flop_3sync* prim_flop_4sync*}]] -min_depth 2

# TODO: Review/confirm if we want 2 or 3 stages for the synchronizers
# Verify detected synchronizers have at least 2 stages.
configure_cdc_nff_sync -depth 2 -detect_insufficient_depth_nff true

################################################################################
# VERIFIED CDC IP BLOCKS
################################################################################
# configure_ip_block -type {cdc} tells SpyGlass to treat these as verified
# CDC modules — skip internal analysis but understand they perform CDC.
# Use explicit module names, not wildcards, to avoid accidental matching.

# AXI CDC chain: axi_cdc_intf → axi_cdc → axi_cdc_src/dst → cdc_fifo_gray_*
configure_ip_block -names [cdc_mod {axi_cdc_intf}] -type {cdc}
configure_ip_block -names [cdc_mod {axi_cdc}] -type {cdc}
configure_ip_block -names [cdc_mod {axi_cdc_src}] -type {cdc}
configure_ip_block -names [cdc_mod {axi_cdc_dst}] -type {cdc}

# APB CDC chain: apb_cdc_intf → apb_cdc → cdc_fifo_gray
# Note: We are not using APB CDC in this design, but it is still a valid CDC module
# configure_ip_block -names {apb_cdc_intf} -type {cdc}

# CDC FIFO primitives (common_cells library)
configure_ip_block -names [cdc_mod {cdc_fifo_gray}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_fifo_gray_src}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_fifo_gray_dst}] -type {cdc}

# Clearable variants of common_cells CDC suite
configure_ip_block -names [cdc_mod {axi_cdc_clearable}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_fifo_gray_clearable}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_fifo_gray_src_clearable}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_fifo_gray_dst_clearable}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_reset_ctrlr}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_reset_ctrlr_half}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_4phase}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_4phase_src}] -type {cdc}
configure_ip_block -names [cdc_mod {cdc_4phase_dst}] -type {cdc}

# Handshake-based data synchronizer, used in AVS Bus
configure_ip_block -names [cdc_mod {prim_sync_data_autohs}] -type {cdc}

################################################################################
# cdc_reset_ctrlr FLUSH-STATE DISTRIBUTION
################################################################################
# The cdc_reset_ctrlr (common_cells) sequences a flush of both sides of a
# clearable CDC FIFO through a 4-phase-synchronized state machine.
# By construction both FIFO sides are held in isolate/clear for the whole state
# transition, so no live data can capture an intermediate value
set cdc_rstctrl_state_src [list]
foreach _rstctrl_cell [get_object_name [get_cells -hier -filter "ref_name =~ ${::MODPREFIX}cdc_4phase_src*" -quiet]] {
    if { [string match {*i_cdc_reset_ctrlr*} $_rstctrl_cell] } {
        set _p [get_pins "$_rstctrl_cell/data_src_q/Q" -quiet]
        if { [sizeof_collection $_p] > 0 } {
            foreach _n [get_object_name $_p] { lappend cdc_rstctrl_state_src $_n }
        }
    }
}
if { [llength $cdc_rstctrl_state_src] > 0 } {
    set_cdc_ignore_path -from $cdc_rstctrl_state_src -type {cdc_crossing glitch} \
        -comments "cdc_reset_ctrlr sequenced-flush state distribution: both FIFO sides are isolated/cleared during every state transition (PULP common_cells verified IP)."
    puts "INFO: Ignoring crossings from [llength $cdc_rstctrl_state_src] cdc_reset_ctrlr flush-state pins"
} else {
    puts "INFO: no cdc_reset_ctrlr flush-state pins found (no clearable CDC in this design)"
}
unset -nocomplain _rstctrl_cell _p _n

### cnt_update_async_fifo (count-update preload FIFO)
# OpenTitan prim_fifo_async (depth 1) carrying the SW count-update value into
# the refclk domain, instance name unique to prim_refclk_count_w_cdc. Gray-coded
# pointer sync via prim_flop_2sync (already UDS-listed above); storage array and
# pointer convergence need targeted constraints to suppress false violations.
#
# RTL signals (per instance) we constrain:
#   - fifo_wptr_gray_q / fifo_rptr_gray_q : source-side gray pointer flops
#   - sync_wptr/u_sync_2/q_o / sync_rptr/u_sync_2/q_o
#       : synced gray pointer outputs (prim_flop_2sync, one cell per bit)
#   - storage[Depth] : data array, written on wclk, read combinationally on rclk
#
# The running counter readback (`gray_count_sync` through the per-bit
# `u_sync_ref_count`) is not declared gray: a count update loads an arbitrary
# value in one refclk cycle, so the readback is gray-coded only between updates.

set cnt_update_fifo_cells [get_cells -hier *u_cnt_update_async_fifo -quiet]
if { [sizeof_collection $cnt_update_fifo_cells] > 0 } {
    foreach cell_hier [get_object_name $cnt_update_fifo_cells] {
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

        # Synced gray pointer outputs (prim_flop_2sync output stage).
        set wptr_sync_pins [get_pins "$cell_hier/sync_wptr/u_sync_2/q_o/Q[0]" -quiet]
        set rptr_sync_pins [get_pins "$cell_hier/sync_rptr/u_sync_2/q_o/Q[0]" -quiet]
        if { [sizeof_collection [get_pins "$cell_hier/sync_wptr/u_sync_2/q_o/Q[1]" -quiet]] > 0 } {
            puts "WARNING: cnt_update_async_fifo ($cell_hier): pointer is wider than 1 bit -- only bit 0 is constrained; extend this section"
        }
        if { [sizeof_collection $wptr_sync_pins] > 0 } {
            set_gray_signals -gray_signals $wptr_sync_pins
            cdc_conv_ignore_among $wptr_sync_pins
        }
        if { [sizeof_collection $rptr_sync_pins] > 0 } {
            set_gray_signals -gray_signals $rptr_sync_pins
            cdc_conv_ignore_among $rptr_sync_pins
        }

        # Read data output: rdata_o bits share a single read pointer.
        set rd_data_pins [get_pins "$cell_hier/rdata_o" -quiet]
        if { [sizeof_collection $rd_data_pins] > 0 } {
            cdc_conv_ignore_among $rd_data_pins
        }
    }

    puts "INFO: Configured [sizeof_collection $cnt_update_fifo_cells] cnt_update_async_fifo instances"
}

puts "INFO: Shared CDC/RDC setup loaded."
