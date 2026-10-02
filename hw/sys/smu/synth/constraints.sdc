# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMU (System Management Unit) block-level timing constraints.
#
# SMU is the top-level integration wrapper for SMC (System Management
# Controller), DTP (Debug and Trace Processor), and SEP (Secure Execution
# Processor, optional via the `SEP` parameter).
#
# Clock periods, generated clocks, clock groups, and I/O delays for every
# `smu` top-level port, validated against the `smu` top-level port list
# (hw/sys/smu/rtl/smu.sv) and its DTP/SMC/SEP sub-instances.
#
# This file composes the sourced sections; the constraints themselves live in
# the sibling files and in flows/synth/constraints, and every one of them is
# shared with the closed block flow, which sources the same files rather than
# keeping a second copy. The GPIO padring is SMC's, passed through unchanged,
# so smu_io_delays.sdc sources SMC's own file for it.
#
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2/abc.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
# (e.g. OpenROAD/OpenSTA) is added to the flow. See
# flows/synth/yosys/README.md for the rationale.
#
# Subcomponent hierarchy mode: this file supports a `smu_sam_flow` switch,
# shared by synth / CDC / RDC signoff.
#   smu_sam_flow == 0 (default, synth): SMC/DTP/SEP RTL is fully present, so
#     constraints reaching INTO subcomponent hierarchy (the AVS clock-mux /
#     divider pins inside u_smc/...) are applied. This is the mode relevant
#     to the current RTL-only flow in this repo.
#   smu_sam_flow == 1 (CDC/RDC): subcomponents are blackboxed and replaced by
#     signoff abstract models (SAM); those into-hierarchy pins do not exist,
#     so the full-hierarchy block is skipped and a simpler feedthrough model
#     is used instead. Not exercised by this repo today, kept for parity
#     with any future SAM-based signoff flow.
#
# Caveats, called out explicitly:
#   - `sep_crypto_entropy_req_o*` / `sep_crypto_entropy_rsp_i*` are commented
#     out below: no generic SEP crypto/entropy passthrough is exposed at the
#     current `smu` top level in this RTL (SEP only surfaces the PKA
#     imem/dmem SRAM and Key Manager ROM/SRAM interfaces).
#   - `sep_security_disable_i` is commented out below: `sep_security_disable`
#     is purely an internal net here (driven by `u_sep.security_disable_o`,
#     consumed by `u_smc.sep_security_disable_i`), not a top-level port.
#   - I/O delays are added below for real `smu` top-level ports with no
#     matching constraint elsewhere: `smc_global_base_o*`,
#     `sep_global_base_o*`, `sep_region_size_o*`, `gpio_interrupt_o*`,
#     `uart_interrupt_o*`, `i3c_dat_mem_sink_o*`, `i3c_dct_mem_sink_o*`,
#     `jtag_ic_reset_ext_o*`, `sep_ext_interrupts_i`, `abr_mem_req_o*` /
#     `abr_mem_rsp_i*`, and the `ext_trng_*` interface.
#   - SPI takes no protocol timing here. The SPI sections of SMC's GPIO file
#     need `spi_clk_i` and the `spi_rxd_o` / `spi_rxds_o` read ports, none of
#     which `smu` exposes, so those pads keep the generic feedthrough model.
#   - The `AVS_DIV_CLK_Q_FROM_*` generated clocks below target the `div_clk`
#     register inside `prim_prog_clk_div_posedge` (reached via
#     `u_smc/u_smc_peripherals/u_avsbus_controller/...`) by name. In this RTL
#     that register is a plain `always_ff`-inferred flop (no discrete
#     primitive instance called `div_clk`), so the pin only resolves
#     post-synthesis once technology mapping assigns it a cell name; it will
#     not resolve against the elaborated RTL.
#   - CDC crossings are bounded in two layers, both included from this file.
#     `set_async_clock_groups` below declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `smu_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. This is separate from the
#     CDC/RDC signoff notes above, which concern how individual crossings are
#     modeled or waived, not how they are bounded. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
#   - `smu_cdc_max_delay_generated.tcl` enumerates this block's CDC elements.
#     It is produced once, offline, against an elaborated design and checked
#     in; nothing discovers instances when this file is read. Its paths and
#     clock names are OCAH's, so instantiating this block deeper in a
#     hierarchy or driving it from differently named clocks needs no edit
#     here -- set `::cdc_hier_prefix` and `::cdc_clock_alias` before sourcing
#     it. Regeneration, which runs in the closed synthesis flow, is needed
#     only when the block is reconfigured such that the set of CDC elements
#     changes: the file then goes stale silently, since no prefix can supply
#     constraints for elements it never listed.
#     It is a full-hierarchy enumeration: under the SAM flow the AVS clocks do
#     not exist, and the calls naming them warn and are skipped.
#     See "CDC Timing Constraints" in the Integrator Guide.
#-----------------------------------------------------------------------------

# Directory holding this file, so the CDC collateral below resolves regardless
# of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smu/synth]
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

source [file join $ocah_sdc_dir smu_clocks.sdc]

##################
# CLOCK GROUPS
##################

source [file join $ocah_sdc_dir smu_clock_groups.sdc]

########################################################
# Input and Output delays
########################################################

source [file join $ocah_sdc_dir smu_io_delays.sdc]

########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir smu_cdc_max_delay.tcl]
