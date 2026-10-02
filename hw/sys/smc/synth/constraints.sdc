# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMC (System Management Controller) block-level timing constraints.
#
# Clock periods, generated clocks, clock groups, and I/O delays for every
# `smc` top-level port, validated against the `smc` top-level port list
# (hw/sys/smc/rtl/smc.sv) and the AVS clock-mux/divider hierarchy
# (hw/ip/avsbus_controller/rtl/avsbus_controller.sv).
#
# This file composes the sourced sections; the constraints themselves live in
# the sibling files and in flows/synth/constraints, and every one of them is
# shared with the closed block flow, which sources the same files rather than
# keeping a second copy.
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2/abc.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Caveats, called out explicitly:
#   - `rst_primary_periph_clk_no` is a real `smc` top-level port; its I/O
#     delay is modeled on its sibling reset outputs.
#   - The `AVS_DIV_CLK_Q_FROM_*` generated clocks target the `div_clk`
#     register inside `prim_prog_clk_div_posedge` by name. In this RTL that
#     register is a plain `always_ff`-inferred flop (no discrete primitive
#     instance called `div_clk`), so the pin only resolves post-synthesis
#     once technology mapping assigns it a cell name; it will not resolve
#     against the elaborated RTL.
#   - CDC crossings are bounded in two layers, both included from this file.
#     smc_clock_groups.sdc declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `smc_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
#   - `smc_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
#     It is produced once, offline, against an elaborated design and checked
#     in; nothing discovers instances when this file is read. Its paths and
#     clock names are OCAH's, so instantiating this block deeper in a
#     hierarchy or driving it from differently named clocks needs no edit
#     here -- set `::cdc_hier_prefix` and `::cdc_clock_alias` before sourcing
#     it. Regeneration, which runs in the closed synthesis flow, is needed
#     only when the block is reconfigured such that the set of CDC elements
#     changes: the file then goes stale silently, since no prefix can supply
#     constraints for elements it never listed.
#     See "CDC Timing Constraints" in the Integrator Guide.
#-----------------------------------------------------------------------------

# Directory holding this file, so the sourced collateral below resolves
# regardless of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smc/synth]
} else {
    error "constraints.sdc: cannot locate this file's directory; set GIT_ROOT"
}
set ocah_flow_constraints_dir [file normalize $ocah_sdc_dir/../../../../flows/synth/constraints]


##################
# CLOCK PERIODS
##################

source [file join $ocah_flow_constraints_dir clock_periods.tcl]

##################
# CLOCK STAMPINGS
##################

source [file join $ocah_sdc_dir smc_clocks.sdc]

##################
# CLOCK GROUPS
##################

source [file join $ocah_sdc_dir smc_clock_groups.sdc]

########################################################
# Input and Output delays
########################################################

source [file join $ocah_sdc_dir smc_io_delays.sdc]
source [file join $ocah_sdc_dir smc_gpio_io_delays.sdc]

########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir smc_cdc_max_delay.tcl]
