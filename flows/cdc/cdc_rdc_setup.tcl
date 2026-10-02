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
        source [file join [file dirname [file normalize [info script]]] vc_procs.tcl]
    } elseif { [info exists ::env(GIT_ROOT)] } {
        source $::env(GIT_ROOT)/flows/cdc/vc_procs.tcl
    } else {
        error "cdc_rdc_setup.tcl: cannot locate vc_procs.tcl; set GIT_ROOT"
    }
}

################################################################################
# HELPER PROCS
################################################################################
# collect_prim_flop_3sync_qpins: collect the per-bit sync-stage Q pins of
# every prim_flop_3sync instance whose hierarchical path matches the supplied
# pattern.
#
# Why this helper exists:
#   prim_sync3 declares `prim_flop_3sync u_sync3 [WIDTH-1:0] (...)` — a
#   generate array of single-bit prim_flop_3sync instances named `u_sync3[0]`,
#   `u_sync3[1]`, etc. The generate brackets `[...]` are NOT matched by the
#   `*` glob in `get_pins -hier`, so a pattern like `*/u_sync3*/d0nt_wrap_sync/Q`
#   silently returns an empty collection. This helper sidesteps the bracket-
#   glob limitation by:
#     1. Filtering cells by `ref_name == prim_flop_3sync` (no bracket
#        glob involved — `ref_name` is module-name match).
#     2. Filtering the resulting cell paths by `string match` against the
#        caller-supplied parent-path pattern (Tcl `string match` does
#        match `[`/`]` literally, unlike SpyGlass's `get_*` glob).
#     3. Building each per-stage pin path explicitly: `<cell>/d0nt_wrap_sync/Q` in the
#        libcell build, `<cell>/q_d/Q` .. `<cell>/q_ddd/Q` in the NO_LIBCELL RTL fallback.
#
# Returns a Tcl list of pin name strings (consumable by `set_gray_signals -gray_signals`
# and `cdc_conv_ignore_among`).
proc collect_prim_flop_3sync_qpins { parent_pattern } {
    set out_pins [list]
    set cells [get_cells -hier -filter "ref_name == prim_flop_3sync" -quiet]
    foreach cname [get_object_name $cells] {
        if { [string match $parent_pattern $cname] } {
            # The libcell build elaborates one 3-stage cell d0nt_wrap_sync; the
            # NO_LIBCELL RTL fallback elaborates per-stage q_d/q_dd/q_ddd.
            foreach stage {q_d q_dd q_ddd d0nt_wrap_sync} {
                set p [get_pins "$cname/$stage/Q" -quiet]
                if { [sizeof_collection $p] > 0 } {
                    foreach n [get_object_name $p] { lappend out_pins $n }
                }
            }
        }
    }
    return $out_pins
}

################################################################################
# GLITCH-FREE CELL CONFIGURATION
################################################################################
# prim_rst_mux2_hf_n: DFT reset bypass mux — override value is stable
# before mux select changes. Blocks append their own modules additively.
configure_glitch_free_cells -ignore_modules {prim_rst_mux2_hf_n}

################################################################################
# SYNCHRONIZER (NFF) CONFIGURATION
################################################################################
# IMPORTANT: Only list actual multi-flop synchronizer LEAF cells here.
# Do NOT include complex CDC modules (pulse syncs, handshakes, FIFOs,
# reset sequencers) — those have internal logic beyond simple FF chains
# and SpyGlass must analyze their internals.

configure_cdc_nff_sync -uds_modules { \
    prim_sync_reset \
    prim_flop_3sync \
    prim_sync2 \
    prim_sync2r \
    prim_sync3 \
    prim_sync3r \
    prim_sync4 \
    prim_sync4r \
    prim_flop_2sync* \
    prim_flop_3sync* \
    prim_flop_4sync*
}

# Async reset synchronizers: these specifically synchronize reset deassertion.
# Blocks append their own async-reset sync modules additively.
configure_cdc_asyncrst_nff_sync -uds_modules {prim_sync_reset}

# RDC synchronizer declaration: set_rdc_synchronizer tells the RDC engine
# that these modules are synchronizers, so RDC crossings with destinations
# inside them are considered blocked. Without this, the tool traces through
# their internal flops and reports false SETUP_RESET_ASSERT_MISSING errors.
set_rdc_synchronizer -sync_cell { \
    prim_sync_reset \
    prim_flop_3sync \
    prim_sync2 \
    prim_sync2r \
    prim_sync3 \
    prim_sync3r \
    prim_sync4 \
    prim_sync4r \
    prim_flop_2sync* \
    prim_flop_3sync* \
    prim_flop_4sync*
} -min_depth 2

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
configure_ip_block -names {axi_cdc_intf} -type {cdc}
configure_ip_block -names {axi_cdc} -type {cdc}
configure_ip_block -names {axi_cdc_src} -type {cdc}
configure_ip_block -names {axi_cdc_dst} -type {cdc}

# APB CDC chain: apb_cdc_intf → apb_cdc → cdc_fifo_gray
# Note: We are not using APB CDC in this design, but it is still a valid CDC module
# configure_ip_block -names {apb_cdc_intf} -type {cdc}

# CDC FIFO primitives (common_cells library)
configure_ip_block -names {cdc_fifo_gray} -type {cdc}
configure_ip_block -names {cdc_fifo_gray_src} -type {cdc}
configure_ip_block -names {cdc_fifo_gray_dst} -type {cdc}

# Clearable variants of common_cells CDC suite
configure_ip_block -names {axi_cdc_clearable} -type {cdc}
configure_ip_block -names {cdc_fifo_gray_clearable} -type {cdc}
configure_ip_block -names {cdc_fifo_gray_src_clearable} -type {cdc}
configure_ip_block -names {cdc_fifo_gray_dst_clearable} -type {cdc}
configure_ip_block -names {cdc_reset_ctrlr} -type {cdc}
configure_ip_block -names {cdc_reset_ctrlr_half} -type {cdc}
configure_ip_block -names {cdc_4phase} -type {cdc}
configure_ip_block -names {cdc_4phase_src} -type {cdc}
configure_ip_block -names {cdc_4phase_dst} -type {cdc}

# Handshake-based data synchronizer, used in AVS Bus
configure_ip_block -names {prim_sync_data_autohs} -type {cdc}

################################################################################
# cdc_reset_ctrlr FLUSH-STATE DISTRIBUTION
################################################################################
# The cdc_reset_ctrlr (common_cells) sequences a flush of both sides of a
# clearable CDC FIFO through a 4-phase-synchronized state machine.
# By construction both FIFO sides are held in isolate/clear for the whole state
# transition, so no live data can capture an intermediate value
set cdc_rstctrl_state_src [list]
foreach _rstctrl_cell [get_object_name [get_cells -hier -filter "ref_name =~ cdc_4phase_src*" -quiet]] {
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

################################################################################
# REFERENCE-COUNTER GRAY SIGNALS (prim_refclk_count_w_cdc)
################################################################################
# prim_gray2bin and sync_ref_count exist only inside prim_refclk_count_w_cdc,
# which is instantiated in both SMC and SEP. get_pins -hier is instance-
# agnostic, so this annotation is a no-op in blocks without the counter.

### prim_gray2bin synchronized-input gray annotation
# prim_gray2bin (hw/common/ocah_prim/rtl/prim_gray2bin.sv) is a pure combinational
# gray-to-binary decoder: z_o[i] = ^a_i[N-1:i]. Each output bit XORs a different
# subset of the input bits, so when the gray-coded `a_i` input is itself the
# output of a per-bit synchronizer chain (e.g. `prim_sync3` over a
# bin2gray-coded counter), static CDC may still flag combinational
# reconvergence at z_o[*]: the same gray bits meet again in the decoder XOR tree.
#
# Functionally this is safe: gray coding guarantees a single-bit transition
# per source-clock edge, so the per-bit syncs cannot produce an invalid
# intermediate, and the decoder output is always a coherent binary value
# (one source-clock cycle stale, but that's by construction).
#
# Annotate the `a_i` input pin of every prim_gray2bin instance as gray and
# ignore convergence among those pins. Primary instance: refclk counter inside
# prim_refclk_count_w_cdc.

set gray2bin_inputs [get_pins -hier *u_prim_gray2bin*/a_i -quiet]
if { [sizeof_collection $gray2bin_inputs] > 0 } {
    set_gray_signals -gray_signals $gray2bin_inputs
    cdc_conv_ignore_among $gray2bin_inputs
    puts "INFO: Annotated [sizeof_collection $gray2bin_inputs] prim_gray2bin a_i pins as gray"
}


### prim_gray2bin per-bit synchronizer outputs (refclk_counter)
# The block above marks the `a_i` *input port* of every prim_gray2bin instance as
# gray; port-level gray alone does not always cover inner reconvergence at
# decoder outputs where upstream sources are listed as the per-bit
# `u_sync_ref_count/u_sync3[i]/d0nt_wrap_sync/Q` flops. Annotate those synchronizer Q pins
# explicitly so gray/coherency modeling matches the RTL.
set sync_ref_count_qpins [collect_prim_flop_3sync_qpins {*u_sync_ref_count/u_sync3*}]
if { [llength $sync_ref_count_qpins] > 0 } {
    set_gray_signals -gray_signals $sync_ref_count_qpins
    cdc_conv_ignore_among $sync_ref_count_qpins
    puts "INFO: Annotated [llength $sync_ref_count_qpins] sync_ref_count prim_flop_3sync per-bit Q pins"
}

### gray_count_sync: the SOURCE-domain gray-coded launch register
# ASSUMES gray-coding is guaranteed at this register, so declare it gray at the source
# TODO: should have check that any grey-coded blocks receive a grey-coded source (e.g. sim assertion)
set gray_count_src_pins [get_pins -hier {*gray_count_sync/Q*} -quiet]
if { [sizeof_collection $gray_count_src_pins] > 0 } {
    set_gray_signals -gray_signals $gray_count_src_pins
    cdc_conv_ignore_among $gray_count_src_pins
    puts "INFO: Annotated [sizeof_collection $gray_count_src_pins] gray_count_sync source gray pins"
}

### cnt_update_async_fifo (count-update preload FIFO)
# OpenTitan prim_fifo_async (depth 1) carrying the SW count-update value into
# the refclk domain, instance name unique to prim_refclk_count_w_cdc. Gray-coded
# pointer sync via prim_flop_2sync (already UDS-listed above); storage array and
# pointer convergence need targeted constraints to suppress false violations.
#
# RTL signals (per instance) we constrain:
#   - fifo_wptr_gray_q / fifo_rptr_gray_q : source-side gray pointer flops
#   - sync_wptr/gen_sync[N].d0nt_wrap_sync / sync_rptr/gen_sync[N].d0nt_wrap_sync
#       : synced gray pointer outputs (prim_flop_2sync, one cell per bit)
#   - storage[Depth] : data array, written on wclk, read combinationally on rclk
#
# The depth-1 preload FIFO also shares write-side logic with the separate wide
# prim_sync3 (`sync_ref_count`) used for running counter readback. Static CDC
# may flag sequential reconvergence where synced read-pointer stages and
# ref-count synchronizer stages meet at storage/D. Merge those related sync
# outputs into one convergence-ignore set so coherency relaxation applies only
# among validated, physically related paths under the same parent hierarchy.

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
        set wptr_sync_pins [get_pins "$cell_hier/sync_wptr/gen_sync\[0\].d0nt_wrap_sync/Q" -quiet]
        set rptr_sync_pins [get_pins "$cell_hier/sync_rptr/gen_sync\[0\].d0nt_wrap_sync/Q" -quiet]
        if { [sizeof_collection [get_pins "$cell_hier/sync_wptr/gen_sync\[1\].d0nt_wrap_sync/Q" -quiet]] > 0 } {
            puts "WARNING: cnt_update_async_fifo ($cell_hier): pointer is wider than 1 bit -- only gen_sync\[0\] is constrained; extend this section"
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

        # Sequential reconvergence at storage/D: merge read-pointer sync outputs
        # with the sync_ref_count sync-stage pins under the same parent.
        set fifo_parent [file dirname $cell_hier]
        set sync_ref_pat "*${fifo_parent}/u_sync_ref_count/u_sync3*"
        set sync_ref_qpins [collect_prim_flop_3sync_qpins $sync_ref_pat]
        set reconv_merge [list]
        foreach p [get_object_name $rptr_sync_pins] { lappend reconv_merge $p }
        foreach p $sync_ref_qpins { lappend reconv_merge $p }
        # Convergence suppression keys on the launch registers, so the gray sources
        # feeding this cluster join the set.
        foreach p [get_object_name [get_pins "$cell_hier/fifo_rptr_gray_q*/Q" -quiet]] { lappend reconv_merge $p }
        foreach p [get_object_name [get_pins "$cell_hier/fifo_wptr_gray_q*/Q" -quiet]] { lappend reconv_merge $p }
        foreach p [get_object_name [get_pins "$fifo_parent/gray_count_sync/Q" -quiet]] { lappend reconv_merge $p }
        if { [llength $reconv_merge] > 0 } {
            set_gray_signals -gray_signals $reconv_merge
            cdc_conv_ignore_among $reconv_merge
            puts "INFO: cnt_update_async_fifo ($cell_hier): convergence-ignore among [llength $reconv_merge] pins (sync_rptr + sync_ref_count under $fifo_parent)"
        } else {
            puts "WARNING: cnt_update_async_fifo ($cell_hier): preload/ref-count merge pin list empty (sync_ref_pat=$sync_ref_pat)"
        }
    }

    puts "INFO: Configured [sizeof_collection $cnt_update_fifo_cells] cnt_update_async_fifo instances"
}

puts "INFO: Shared CDC/RDC setup loaded."
