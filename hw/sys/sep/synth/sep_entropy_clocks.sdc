# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP entropy_source internal clock tree.
#
# Not shared with the closed block flow: every lookup below is by hierarchical
# instance path and by standard-cell reference name, both of which differ per
# entropy_source implementation and per target library. A flow with a different
# entropy_source stamps its own tree instead of sourcing this file.
#
# None of these lookups resolve pre-synthesis, and entropy_source inside
# sep_crypto is currently blackboxed, so today this documents the intended
# clock topology rather than constraining anything. Sourced after
# sep_clocks.sdc, which stamps the ENTROPY_ROSC_CLK port clock these reference.
#-----------------------------------------------------------------------------

# shared ring oscillator output buffer pin
set entropy_shared_ro_pin [get_pins "sep_crypto/u_entropy_source/egen/sclk/shared_ro/u_fbf/y_o"]

# entropy_source internal shared ring-oscillator clock
create_clock -add -name ENTROPY_SHARED_RO -period $clock_periods(ENTROPY_SHARED_RO_PERIOD) $entropy_shared_ro_pin

# all toggle-flop cells once; each divider's taps are selected by path below
set entropy_div_flops [lsort -dictionary [get_object_name [get_cells -hierarchical -filter "ref_name == prim_dffrxq"]]]

# entropy_source sample-clock tree (egen/sclk): a length-109 shared ring oscillator
# plus one 5-stage ripple divider per generator. Each divider is fed by a mux between
# the external sample clock (ENTROPY_ROSC_CLK) and the shared RO, so every divider tap
# acts as a clock and is declared from both sources. Divide ratio is immaterial for
# CDC; only the source-clock relationship matters.
# one generated clock per divider tap from each source, numbered in stamping order
set entropy_tap_idx 0
foreach entropy_tap_cell [lsearch -all -inline -glob $entropy_div_flops {*egen/sclk/gen_ecmplx*u_sample_clk_divider*u_div_ff}] {
    set entropy_tap_pin [get_pins "${entropy_tap_cell}/q_o/Q"]
    create_generated_clock -add -name ENTROPY_SCLK_FROM_ROSC_${entropy_tap_idx}      -master_clock ENTROPY_ROSC_CLK  -divide_by 2 -source [get_ports "entropy_rosc_sample_clk_i"] $entropy_tap_pin
    create_generated_clock -add -name ENTROPY_SCLK_FROM_SHARED_RO_${entropy_tap_idx} -master_clock ENTROPY_SHARED_RO -divide_by 2 -source $entropy_shared_ro_pin $entropy_tap_pin
    incr entropy_tap_idx
}

# debug monitor ripple divider (dbg/u_ripple_divider): observability only -- it divides a
# debug-selected internal signal off-chip via signal_monitor_o, never into functional logic.
# The source is a dynamic debug mux, so declare each tap as its own clock and keep the whole
# divider in one async group, isolated from the functional clocks.
set entropy_dbg_tap_idx 0
foreach entropy_dbg_cell [lsearch -all -inline -glob $entropy_div_flops {*dbg/u_ripple_divider*u_div_ff}] {
    create_clock -add -name ENTROPY_DBG_MON_${entropy_dbg_tap_idx} -period $clock_periods(ENTROPY_ROSC_PERIOD) [get_pins "${entropy_dbg_cell}/q_o/Q"]
    incr entropy_dbg_tap_idx
}

# the source mux passes the external clock or the shared RO into each divider, never both,
# so they are exclusive at every mux. Across generators the two families are not strictly
# exclusive (one generator can run external while another runs shared), but they never
# converge anywhere outside these muxes, so grouping each master plus its taps as
# logically_exclusive only suppresses analysis where the two sources actually mux -- safe
set_clock_groups -logically_exclusive \
    -group [concat {ENTROPY_ROSC_CLK}  [get_object_name [get_clocks "ENTROPY_SCLK_FROM_ROSC_*"]]] \
    -group [concat {ENTROPY_SHARED_RO} [get_object_name [get_clocks "ENTROPY_SCLK_FROM_SHARED_RO_*"]]]
