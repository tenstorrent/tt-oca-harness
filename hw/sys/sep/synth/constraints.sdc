# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP (Security Processor) block-level timing constraints.
#
# Clock periods, generated clocks, and I/O delays for the `sep` top-level
# port list (hw/sys/sep/rtl/sep.sv). All top-level port references below
# match the current RTL with no renames.
#
# This file composes the sourced sections; the constraints themselves live in
# the sibling files and in flows/synth/constraints. Everything except the
# entropy clock tree is shared with the closed block flow, which sources the
# same files rather than keeping a second copy.
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (flows/synth/pdk/ihp-sg13g2/yosys/abc.constr) rather than a full SDC. A full
# SDC like this one only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Known limitations, called out explicitly:
#   - The entropy ripple-divider clocks below are created from the RTL
#     hierarchy when `entropy_source` is elaborated. The section is skipped
#     when the shared ring-oscillator pin is absent (the block is
#     blackboxed). When that pin is present, a short tap count is an error:
#     every divided flop must carry a generated clock.
#   - CDC crossings are bounded in two layers, both included from this file.
#     sep_clock_groups.sdc declares the asynchronous groups with `-allow_paths`
#     and applies a loose default max_delay per inter-group clock pair;
#     `sep_cdc_max_delay.tcl`, sourced at the end, tightens each synchronizer
#     and async FIFO individually. The `-allow_paths` is not optional:
#     `set_false_path` outranks `set_max_delay` in exception priority, so a bare
#     `set_clock_groups -asynchronous` would silently mask every per-instance
#     bound.
#   - `sep_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
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
# regardless of the invoking tool's working directory. `info script` is the file
# currently being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/sep/synth]
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

source [file join $ocah_sdc_dir sep_clocks.sdc]
source [file join $ocah_sdc_dir sep_entropy_clocks.sdc]

##################
# CLOCK GROUPS
##################

source [file join $ocah_sdc_dir sep_clock_groups.sdc]

########################################################
# Input and Output delays
########################################################

source [file join $ocah_sdc_dir sep_io_delays.sdc]

########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by sep_clock_groups.sdc above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir sep_cdc_max_delay.tcl]
