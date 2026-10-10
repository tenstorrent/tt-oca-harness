# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# DTP (Debug and Test Ports) block-level timing constraints.
#
# Clock periods, generated clocks, and I/O delays for the `dtp` top-level
# port list (hw/sys/dtp/rtl/dtp.sv).
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (flows/synth/pdk/ihp-sg13g2/yosys/abc.constr) rather than a full SDC. A full
# SDC like this one only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Caveats, called out explicitly:
#   - `dtp` exposes three typed per-slice IC-reset ports,
#     `jtag_ic_reset_smc_o`, `jtag_ic_reset_sep_o`, and `jtag_ic_reset_ext_o`
#     (each with `.ovrd`/`.val` sub-structs); the constraints below cover all
#     three.
#   - `cla_clock_stop_en_o` and the DFT ports `test_en_i`/`scan_rst_ni` are
#     real `dtp` top-level ports; constraints below are modeled on their
#     nearest siblings (`stop_clks_o` and the SMC block's JTAG_TCK-domain DFT
#     ports, respectively).
#   - CDC crossings are bounded in two layers, both included from this file.
#     `set_async_clock_groups` below declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `dtp_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
#   - `dtp_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
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

# Directory holding this file, so the CDC collateral below resolves regardless
# of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/dtp/synth]
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

source [file join $ocah_sdc_dir dtp_clocks.sdc]

########################################################
# Async clock groups
########################################################

source [file join $ocah_sdc_dir dtp_clock_groups.sdc]

########################################################
# Input and Output delays
########################################################

source [file join $ocah_sdc_dir dtp_io_delays.sdc]

########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir dtp_cdc_max_delay.tcl]
