# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP entropy_source ripple-divider clocks.
#
# Not shared with the closed block flow: every lookup is by hierarchical
# instance path and by cell reference name, both of which differ per
# entropy_source implementation and per target library. A flow with a different
# entropy_source stamps its own tree instead of sourcing this file.
#
# Sourced after sep_clocks.sdc, which stamps the ENTROPY_ROSC_CLK port clock
# these reference.
#-----------------------------------------------------------------------------
# Twelve sampler lanes, five ripple stages each, plus the debug monitor's
# seven-stage divider. Stage n is Q of gen_div_stage n and divides the selected
# source by 2^(n+1). The flop Q is not a clock cell, so each tap is declared
# here. Both sampler sources are stamped: the lane mux selects one of them.
set entropy_shared_ro_pins [get_pins -quiet \
    "u_sep_crypto/u_sep_trng/u_entropy_source_s3c_scan/u_generator_complex/u_sampler_clocks/u_shared_ro/u_fbf/y_o"]

if {[sizeof_collection $entropy_shared_ro_pins] == 0} {
    puts "INFO: entropy_source is absent; ripple-divider generated clocks skipped"
} else {
    set entropy_shared_ro_pin [lindex [get_object_name $entropy_shared_ro_pins] 0]
    create_clock -add -name ENTROPY_SHARED_RO \
        -period $clock_periods(ENTROPY_SHARED_RO_PERIOD) $entropy_shared_ro_pin

    set entropy_ref_cells [get_cells -hierarchical -quiet -filter "ref_name =~ prim_flop*"]
    set entropy_div_flops {}
    if {[sizeof_collection $entropy_ref_cells] > 0} {
        set entropy_div_flops [get_object_name $entropy_ref_cells]
    }
    set entropy_sampler_flops [lsearch -all -inline -glob $entropy_div_flops \
        {*u_sampler_clocks*u_sample_clk_divider*u_div_ff}]
    if {[llength $entropy_sampler_flops] == 0} {
        set entropy_sampler_cells [get_cells -hierarchical -quiet \
            *u_sampler_clocks*u_sample_clk_divider*u_div_ff]
        if {[sizeof_collection $entropy_sampler_cells] > 0} {
            set entropy_sampler_flops [get_object_name $entropy_sampler_cells]
        }
    }
    set entropy_sampler_flops [lsort -dictionary $entropy_sampler_flops]

    set entropy_tap_idx 0
    foreach entropy_tap_cell $entropy_sampler_flops {
        if {![regexp {gen_div_stage\[([0-9]+)\]|gen_div_stage_([0-9]+)} \
                $entropy_tap_cell -> entropy_stage_b entropy_stage_u]} {
            error "entropy divider flop has no stage index: $entropy_tap_cell"
        }
        set entropy_stage $entropy_stage_b
        if {$entropy_stage eq ""} {
            set entropy_stage $entropy_stage_u
        }
        set entropy_divide_by [expr {1 << ($entropy_stage + 1)}]
        set entropy_tap_pin [get_pins "${entropy_tap_cell}/q_o"]
        create_generated_clock -add -name ENTROPY_SCLK_FROM_ROSC_${entropy_tap_idx} \
            -master_clock ENTROPY_ROSC_CLK -divide_by $entropy_divide_by \
            -source [get_ports "entropy_rosc_sample_clk_i"] $entropy_tap_pin
        create_generated_clock -add -name ENTROPY_SCLK_FROM_SHARED_RO_${entropy_tap_idx} \
            -master_clock ENTROPY_SHARED_RO -divide_by $entropy_divide_by \
            -source $entropy_shared_ro_pin $entropy_tap_pin
        incr entropy_tap_idx
    }
    if {$entropy_tap_idx != 60} {
        error "entropy sampler divider taps: expected 60, found $entropy_tap_idx"
    }

    # Debug-monitor divider: observability only. Its source is a debug mux, so
    # each tap is its own clock and the group below keeps it off the functional
    # clocks.
    set entropy_dbg_flops [lsearch -all -inline -glob $entropy_div_flops \
        {*u_debug_monitor*u_ripple_divider*u_div_ff}]
    if {[llength $entropy_dbg_flops] == 0} {
        set entropy_dbg_cells [get_cells -hierarchical -quiet \
            *u_debug_monitor*u_ripple_divider*u_div_ff]
        if {[sizeof_collection $entropy_dbg_cells] > 0} {
            set entropy_dbg_flops [get_object_name $entropy_dbg_cells]
        }
    }
    set entropy_dbg_flops [lsort -dictionary $entropy_dbg_flops]
    set entropy_dbg_tap_idx 0
    foreach entropy_dbg_cell $entropy_dbg_flops {
        create_clock -add -name ENTROPY_DBG_MON_${entropy_dbg_tap_idx} \
            -period $clock_periods(ENTROPY_ROSC_PERIOD) \
            [get_pins "${entropy_dbg_cell}/q_o"]
        incr entropy_dbg_tap_idx
    }
    if {$entropy_dbg_tap_idx != 7} {
        error "entropy debug divider taps: expected 7, found $entropy_dbg_tap_idx"
    }

    # The source mux passes one of the two clocks into each divider. The two
    # families do not converge outside those muxes.
    set_clock_groups -logically_exclusive \
        -group [concat {ENTROPY_ROSC_CLK} \
            [get_object_name [get_clocks "ENTROPY_SCLK_FROM_ROSC_*"]]] \
        -group [concat {ENTROPY_SHARED_RO} \
            [get_object_name [get_clocks "ENTROPY_SCLK_FROM_SHARED_RO_*"]]]
}
