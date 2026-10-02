# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#-----------------------------------------------------------------------------
# SMU (System Management Unit) block-level timing constraints.
#
# SMU is the top-level integration wrapper for SMC (System Management
# Controller), DTP (Debug and Test Ports), and SEP (Security Processor,
# optional via the `SEP` parameter).
#
# Clocks, generated clocks, clock groups, and I/O delays for every `smu`
# top-level port (hw/sys/smu/rtl/smu.sv) and its DTP/SMC/SEP sub-instances.
#
# Read by synthesis as the block SDC, by the CDC/RDC sign-off run through
# cdc/smu.cdc_rdc.tcl, and by any parent that replays this block under a
# hierarchy prefix (hw/sys/smu). Clock periods come from
# flows/synth/constraints/clock_periods.tcl; the hooks from cdc_hier_procs.tcl.
#
# Subcomponent constraint mode (`smu_inherit_children`):
#   0 (default, synth): this file carries its own copy of the into-hierarchy
#     constraints (the AVS clock tree inside u_smc/...) and applies its own
#     clock groups.
#   1 (CDC/RDC sign-off, set by cdc/smu.cdc_rdc.tcl): the run is flat and
#     inherits the subcomponent constraints by replaying SMC/DTP/SEP's own
#     files under an instance prefix. The AVS copy below is skipped (it comes
#     from hw/sys/smc/synth/constraints.sdc re-anchored at u_smc/) and the
#     clock-group application is deferred to the entry's single merged
#     cdc_apply_async_groups.
#
# Caveats, called out explicitly:
#   - `sep_crypto_entropy_req_o*` / `sep_crypto_entropy_rsp_i*` are commented
#     out below: no generic SEP crypto/entropy passthrough is exposed at the
#     current `smu` top level in this RTL.
#   - `sep_security_disable_i` is commented out below: `sep_security_disable`
#     is purely an internal net here, not a top-level port.
#   - CDC crossings are bounded in two layers. `cdc_apply_async_groups` below
#     declares the asynchronous groups; in the synth scenario it goes through
#     `set_async_clock_groups`, which adds `-allow_paths` and a loose default
#     max_delay per inter-group clock pair, and `smu_cdc_max_delay.tcl`,
#     sourced at the end, tightens each synchronizer and async FIFO
#     individually. The `-allow_paths` is not optional: `set_false_path`
#     outranks `set_max_delay` in exception priority, so a bare
#     `set_clock_groups -asynchronous` would silently mask every per-instance
#     bound. The functional (sign-off) scenario emits the bare form and skips
#     the bounds.
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
#     See "CDC Timing Constraints" in the Integrator Guide.
#-----------------------------------------------------------------------------

# Directory holding this file, so the shared collateral below resolves regardless
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

# Clock periods and the hierarchy-reuse hooks every constraint below goes through.
source [file join $ocah_flow_constraints_dir clock_periods.tcl]
if {[info procs cdc_is_block_top] eq ""} {
    source [file join $ocah_flow_constraints_dir cdc_hier_procs.tcl]
}

# The two AVS clock families are related -logically_exclusive below; keep that
# pair out of the asynchronous declaration in the synth scenario (a pair cannot
# carry both relationships).
set ::cdc_async_exclude {{AVS_*_FROM_REFCLK* AVS_*_FROM_PERIPHERALCLK*}}

# Standalone read (synthesis) unless the SMU sign-off entry set it; see the
# subcomponent constraint mode in the header.
if {![info exists smu_inherit_children]} { set smu_inherit_children 0 }


##################
# CLOCK STAMPINGS
##################

create_clock -add -name REFCLK            -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name SMUCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_smu_i"]
create_clock -add -name PERIPHERALCLK     -period $clock_periods(PERIPHERALCLK_PERIOD)         [get_ports "clk_periph_i"]
create_clock -add -name TELEMETRYCLK      -period $clock_periods(TELEMETRYCLK_PERIOD)          [get_ports "clk_telemetry_i"]
create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"]

# This clock can by any of the plls clocks, it is pushed to the GPIO for observability.
# create_clock -add -name PLL_CLK_OBS               -period $clock_periods(SYSCLK_PERIOD)                [get_ports "pll_clk_obs_i"]
# create_clock -add -name PVT_PROCESS_CLK_OBS       -period $clock_periods(SYSCLK_PERIOD)                [get_ports "pvt_process_clk_obs_i"]

# JTAG STAP generated clocks (TCK outputs from DTP)
create_generated_clock [get_ports {jtag_stap_io_host_tap_ctrl_o*tck*}] \
    -name JTAG_STAP_IO_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

# Extra STAP TCK outputs (parameterized array - will match 0 or more ports)
create_generated_clock [get_ports {jtag_stap_extra_host_tap_ctrl_o*tck*}] \
    -name JTAG_STAP_EXTRA_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational \
    -add

# JTAG Scan Control (jtag_scan_ctrl_t) generated clocks
create_generated_clock [get_ports {jtag_bsr_host_scan_ctrl_o*tck*}] \
    -name JTAG_BSR_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_stap_host_scan_ctrl_o*tck*}] \
    -name JTAG_STAP_SCAN_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_dfd_host_scan_ctrl_o*tck*}] \
    -name JTAG_DFD_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_dft_secure_host_scan_ctrl_o*tck*}] \
    -name JTAG_DFT_SECURE_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

create_generated_clock [get_ports {jtag_dft_host_scan_ctrl_o*tck*}] \
    -name JTAG_DFT_TCK \
    -master_clock JTAG_TCK \
    -divide_by 1 \
    -source [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"] \
    -combinational

# NOTE: observed-clock core2pad bits (e.g. [55]/[57] PLL_CLK_OBS / PVT_PROCESS_CLK_OBS)
# are -- like every other core2pad bit -- covered by the port-based
# set_cdc_ignore_path -type {glitch clock_path_glitch} in the inherited
# smc_cdc_rdc_setup.tcl, which SMC writes specifically to cover bits that behave as
# exported clocks under muxing.

# memories
create_generated_clock [get_ports smc_rom_intf_req_o*clk] -name SMUCLK_ROM -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_scratch_ram_intf_req_o?0*clk]  -name SMUCLK_RAM0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?1*clk]  -name SMUCLK_RAM1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?2*clk]  -name SMUCLK_RAM2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?3*clk]  -name SMUCLK_RAM3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?4*clk]  -name SMUCLK_RAM4  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?5*clk]  -name SMUCLK_RAM5  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?6*clk]  -name SMUCLK_RAM6  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?7*clk]  -name SMUCLK_RAM7  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?8*clk]  -name SMUCLK_RAM8  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?9*clk]  -name SMUCLK_RAM9  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?10*clk] -name SMUCLK_RAM10 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?11*clk] -name SMUCLK_RAM11 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?12*clk] -name SMUCLK_RAM12 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?13*clk] -name SMUCLK_RAM13 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?14*clk] -name SMUCLK_RAM14 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?15*clk] -name SMUCLK_RAM15 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?16*clk] -name SMUCLK_RAM16 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?17*clk] -name SMUCLK_RAM17 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?18*clk] -name SMUCLK_RAM18 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?19*clk] -name SMUCLK_RAM19 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?20*clk] -name SMUCLK_RAM20 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?21*clk] -name SMUCLK_RAM21 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?22*clk] -name SMUCLK_RAM22 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?23*clk] -name SMUCLK_RAM23 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?24*clk] -name SMUCLK_RAM24 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?25*clk] -name SMUCLK_RAM25 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?26*clk] -name SMUCLK_RAM26 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?27*clk] -name SMUCLK_RAM27 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?28*clk] -name SMUCLK_RAM28 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?29*clk] -name SMUCLK_RAM29 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?30*clk] -name SMUCLK_RAM30 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_scratch_ram_intf_req_o?31*clk] -name SMUCLK_RAM31 -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?0*clk]  -name SMUCLK_ICACHE_TAG0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?1*clk]  -name SMUCLK_ICACHE_TAG1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?2*clk]  -name SMUCLK_ICACHE_TAG2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o?3*clk]  -name SMUCLK_ICACHE_TAG3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?0*clk]  -name SMUCLK_ICACHE_DATA0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?1*clk]  -name SMUCLK_ICACHE_DATA1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?2*clk]  -name SMUCLK_ICACHE_DATA2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?3*clk]  -name SMUCLK_ICACHE_DATA3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?4*clk]  -name SMUCLK_ICACHE_DATA4  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?5*clk]  -name SMUCLK_ICACHE_DATA5  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?6*clk]  -name SMUCLK_ICACHE_DATA6  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o?7*clk]  -name SMUCLK_ICACHE_DATA7  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?0*clk]  -name SMUCLK_DCACHE_TAG0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?1*clk]  -name SMUCLK_DCACHE_TAG1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?2*clk]  -name SMUCLK_DCACHE_TAG2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o?3*clk]  -name SMUCLK_DCACHE_TAG3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?0*clk]  -name SMUCLK_DCACHE_DATA0  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?1*clk]  -name SMUCLK_DCACHE_DATA1  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?2*clk]  -name SMUCLK_DCACHE_DATA2  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o?3*clk]  -name SMUCLK_DCACHE_DATA3  -master_clock SMUCLK -divide_by 1 -source [get_ports "clk_smu_i"] -combinational

# When inheriting (flat CDC/RDC), the AVS clock tree below comes from
# hw/sys/smc/synth/constraints.sdc re-anchored at u_smc/ -- this synth-only copy is skipped.
# Follow-up: converge the synth flow onto inheritance too, then delete this copy.
if {!$smu_inherit_children} {
############################
# AVS Clock Constraints
############################
# Note: For STA you need to care about the divided value (it is a programmable clock divider), but for CDC setup the fact its a divided value is all that matters
set avs_hier u_smc/u_smc_peripherals/u_avsbus_controller

# Refclk and periph clock both fed into a clock mux
# I will create a generated clock on the output of the clockmux for both possible sources
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 1 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 1 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"]

# Tell the tool the raw primaries stop at the mux output — the generated clocks take over from there
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    -clocks {REFCLK PERIPHERALCLK}

# Now the clock mux output is fed into a clock divider.
# Important RTL nuance: `prim_prog_clk_div_posedge` can also bypass the divider
# internally, so `avs_clock_o` may be launched either by the muxed parent clock
# or by the divided clock depending on mode.
# AVS clock when sourced from REFCLK (modes 10/11, DEFAULT)
create_generated_clock -add -name AVS_CLK_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"]

# AVS clock when sourced from PERIPHERALCLK (modes 00/01)
create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"]

# Same divided-clock intent on `u_clk_div/clk_o` (`pre_testmux_avs_clk`) so VC
# Static does not flag SETUP_CLOCK_UNDECL when propagation from u_div_clk_stdbuf/y_o
# alone does not reach the module output pin (prim_prog_clk_div_posedge).
create_generated_clock -add -name AVS_CLK_DIV_CLK_O_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/clk_o"]

create_generated_clock -add -name AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/clk_o"]

# Internal `div_clk` net (flop -> prim_stdbuf a_i): VC otherwise reports SETUP_CLOCK_UNDECL
# looking for a non-existent `div_clk/Q`; stamping a_i matches energy already modeled at y_o.
create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/a_i"]

create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/a_i"]

# Toggle flop output (feeds div_clk_stdbuf and postdiv_mux clk1_i). VC reports
# SETUP_CLOCK_UNDECL on net .../div_clk with PotentialRoot .../div_clk/Q when
# no generated clock is stamped on that pin; a_i/y_o/clk_o alone are not always
# enough for setup clock resolution on the internal net.
create_generated_clock -add -name AVS_DIV_CLK_Q_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/div_clk/Q"]

create_generated_clock -add -name AVS_DIV_CLK_Q_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/div_clk/Q"]

# apply generated clock to the final gpio output pin as well
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports "core2pad_o[49]"]

create_generated_clock -add -name AVS_CLK_FROM_REFCLK_GPIO \
    -master_clock AVS_CLK_FROM_REFCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"] \
    [get_ports "core2pad_o[49]"]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports "core2pad_o[49]"]

create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLK_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_stdbuf/y_o"] \
    [get_ports "core2pad_o[49]"]

# Downstream AVS flops should resolve against `AVS_CLK_FROM_REFCLK` /
# `AVS_CLK_FROM_PERIPHERALCLK` families, which are `-logically_exclusive` below
# (only one premux source mode is active at a time).
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_clk_div/u_postdiv_mux/clk_o"] \
    -clocks {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK}

# Check about these being in the same group
# These two can never be active simultaneously (muxed sources)
set_clock_groups -logically_exclusive \
    -group {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO} \
    -group {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
}

# SEP WDT clock
create_clock -add -name SEP_WDT_CLK -period $clock_periods(REFCLK_PERIOD) [get_ports "clk_sep_wdt_i"]

# I2C
# controller uses PERIPHCLK + a counter to create output SCL, there is no logic based on SCL output
# input SCL is also not used as a clock

# UART
# no clock divider used to generate UART baud rate

# EFUSE
# no clock divider in efuse interface controller

# I3C
# Controller uses PERIPHCLK + a counter to create output SCL, there is no logic based on SCL output
# input SCL is also not used as a clock

# feedthrough clock for any async input/outputs
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)

# Async-domain membership: register SMU's generated clocks into their canonical domains.
cdc_group_extra JTAG_TCK {JTAG_STAP_IO_TCK JTAG_STAP_EXTRA_TCK JTAG_BSR_TCK JTAG_STAP_SCAN_TCK JTAG_DFD_TCK JTAG_DFT_SECURE_TCK JTAG_DFT_TCK}

# The mem/ROM/cache output clocks are -combinational /1 copies of SMUCLK: same domain.
set _smu_mem_clks [list SMUCLK_ROM]
for {set i 0} {$i < 32} {incr i} { lappend _smu_mem_clks SMUCLK_RAM$i }
for {set i 0} {$i < 4}  {incr i} { lappend _smu_mem_clks SMUCLK_ICACHE_TAG$i SMUCLK_DCACHE_TAG$i SMUCLK_DCACHE_DATA$i }
for {set i 0} {$i < 8}  {incr i} { lappend _smu_mem_clks SMUCLK_ICACHE_DATA$i }
cdc_group_extra SMUCLK $_smu_mem_clks
unset _smu_mem_clks

if {!$smu_inherit_children} {
    # Synth-only AVS copy defined above -> register its clocks here; when inheriting,
    # hw/sys/smc/synth/constraints.sdc registers the AVS (and SPI) clocks itself.
    cdc_group_extra REFCLK {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
    cdc_group_extra PERIPHERALCLK {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}

    # Non-inheriting flows (synth) apply the grouping here; the flat CDC/RDC aggregator
    # applies ONE merged set_clock_groups after sourcing every child instead.
    cdc_apply_async_groups {REFCLK SMUCLK PERIPHERALCLK TELEMETRYCLK JTAG_TCK SEP_WDT_CLK ck_feedthru}
}

########################################################
# Input and Output delays
########################################################

# resets
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports powergood_i] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cold_ni] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_cold_stable_ref_clk_no] -add_delay

set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_primary_ref_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports rst_primary_smc_clk_no] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cool_n_from_pin_i] -add_delay

# AXI / AXI-Lite interfaces
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_in_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_out_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smu_axi_out_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_external_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_efuse_shim_command_resp_i*}] -add_delay

# telemetry
# telemetry_afvalid_o is resynchronised into clk_telemetry_i inside telemetry_receiver_wrap,
# so the whole ATB interface (AT and AF channels) is TELEMETRYCLK; SMC stamps it the same
# way (hw/sys/smc/synth/constraints.sdc). Stamped once here to keep the port single-clocked.
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afvalid_o*}] -add_delay

# # pll
# set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports pll_clk_obs_i] -add_delay
# set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports pll_clk_obs_en_i] -add_delay

# # pvt
# set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports pvt_process_clk_obs_i] -add_delay
# set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports pvt_process_clk_obs_en_i] -add_delay

# # cat trip
# set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cat_therm_i] -add_delay

# GPIO Data Signals
# GPIO I/O delays come from hw/sys/smc/synth/gpio_io_constraints.sdc, sourced at the end of
# this file in standalone mode and replayed from the inherited SMC constraints otherwise.

# telemetry
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports rst_telemetry_ni] -add_delay

set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atdata_i*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atready_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atvalid_i*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afready_i*}] -add_delay

# WDT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_wdt_first_timeout_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_wdt_second_timeout_o] -add_delay

# interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ext_interrupts_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_ext_mailbox_interrupts_o*}] -add_delay

# efuse
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_shadow_regs_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_fuse_sense_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_fuse_reset_n_delayed_o] -add_delay

# DFT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports skip_mem_repair_o] -add_delay

# LC
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {lc_state_o*}] -add_delay

# RAS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_cluster_ded_o] -add_delay

# NDM
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ndmreset_request_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_ndmreset_process_o*}] -add_delay

# reset unit
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cfg_flr_pf_active_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {isolate_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ss_reset_complete_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ss_config_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ss_reset_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports sync_irq_o] -add_delay

# will transition once to indicate status of POR DFX logic
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mem_repair_done_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mem_repair_success_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mem_repair_abort_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mbist_done_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mbist_pass_i}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {mbist_abort_i}] -add_delay
# ext_boot_seq_done_i: pinned by smu_case_analysis.tcl in the functional scenario
cdc_pinned_port_delay set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_boot_seq_done_i}] -add_delay

# will transition once as a strap (one time capture on cold reset de-assertion)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_disable_sram_auto_init_i}] -add_delay

# controlled by internal register, expected to set once during boot and not expected to change frequently
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_region_size_o*}] -add_delay

# memory
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_rom_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {smc_rom_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_scratch_ram_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_scratch_ram_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_icache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_icache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_icache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_icache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_dcache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_dcache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [filter_collection [get_ports {smc_l1_dcache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {smc_l1_dcache_data_intf_rsp_i*}] -add_delay

# Trace Memory
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {trace_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {trace_mem_resp_i*}] -add_delay

# OCTS
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports chiplet_is_primary_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {timer_count_o*}] -add_delay

# External Debug Bus
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_debug_bus_i*}] -add_delay

# Test (pinned by smu_case_analysis.tcl in the functional scenario)
cdc_pinned_port_delay set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports scan_rst_ni] -add_delay
cdc_pinned_port_delay set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports test_en_i] -add_delay

# Memory Init
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports smc_init_mem_done_o] -add_delay

########################################################
# JTAG Interface Constraints (SMU-specific)
########################################################

# Each input delay follows the TCK edge that launches the signal and each output
# delay precedes the rising edge that captures it. TDI, TMS, TRST and a
# downstream TAP's TDO change on the falling edge (-clock_fall); host scan-chain
# returns change on the rising edge. `.tck` fields carry generated clocks and
# take no data delay. The budget matches the DTP block constraints.
set jtag_io_ext [expr $clock_periods(JTAG_TCK_PERIOD)*0.2]

# Primary JTAG TAP Interface
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [filter_collection [get_ports {jtag_ptap_client_tap_ctrl_i*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_ptap_client_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_ptap_client_tdo_oen_o] -add_delay

# Boundary Scan Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_bsr_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_bsr_host_scan_out_o] -add_delay

# I/O STAP Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_io_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports jtag_stap_io_host_tdi_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_o] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_io_host_tdo_oen_o] -add_delay

# Extra STAP Interfaces
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_extra_host_tap_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] -clock_fall [get_ports {jtag_stap_extra_host_tdi_i*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_stap_extra_host_tdo_oen_o*}] -add_delay

# Extended STAP Scan Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_stap_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_stap_host_scan_out_o] -add_delay

# DFD iJTAG Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dfd_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dfd_host_scan_out_o] -add_delay

# Secure DFT iJTAG Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dft_secure_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_secure_host_scan_out_o] -add_delay

# DFT iJTAG Interface
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [filter_collection [get_ports {jtag_dft_host_scan_ctrl_o*}] {name !~ "*tck*"}] -add_delay
set_input_delay  $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_in_i] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports jtag_dft_host_scan_out_o] -add_delay

# JTAG State Outputs
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_state_o*}] -add_delay
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ptap_inst_decoded_o*}] -add_delay

# `jtag_ic_reset_ext_o` is a real `smu` top-level output (the external slice
# of DTP's IC_RESET TDR), modeled the same as the other JTAG_TCK-domain state
# outputs above. Width follows `ic_reset_ext_t`; the integrator carries the SEP
# xSPI reset overrides here, so the wildcard must stay a wildcard.
set_output_delay $jtag_io_ext -clock [get_clock JTAG_TCK] [get_ports {jtag_ic_reset_ext_o*}] -add_delay

# DTP Clock Stop Output
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports dtp_stop_clks_o] -add_delay

########################################################
# Cross Trigger Matrix Constraints (SMU-specific)
########################################################

# Cross Trigger Matrix Interface (external ports [7:0] exposed)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctm_src_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_src_ack_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctm_dst_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctm_dst_ack_o*}] -add_delay

# Clock Stop Request Interface (external ports [7:0] exposed)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_clk_stop_req_i*}] -add_delay

########################################################
# Cross Trigger Port GPIO Constraints (SMU-specific)
########################################################

# Cross Trigger Port GPIO Interface (16 CTPs)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_out_din_en_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_req_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_req_in_din_en_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_in_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_in_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_in_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_in_din_en_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_out_dout_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_out_dout_en_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {xtrig_ctp_ack_out_din_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {xtrig_ctp_ack_out_din_en_o*}] -add_delay

########################################################
# SEP Passthrough Ports (to/from sep_ip_integration in smu_wrapper)
########################################################

# SEP Memory Interfaces
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_boot_rom_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {sep_boot_rom_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_cpu_tcm_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {sep_cpu_tcm_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_imem_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_imem_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_dmem_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_crypto_pka_dmem_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_km_rom_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMUCLK] [get_ports {sep_km_rom_mem_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMUCLK] [get_ports {sep_km_sram_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_km_sram_mem_rsp_i*}] -add_delay

# SEP eFuse Interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_bank_ctrl_resp_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_efuse_shim_command_resp_i*}] -add_delay

# SEP External
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_external_resp_i*}] -add_delay

# SEP CPU Trace
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {sep_cpu_trace_o*}] -add_delay

# LCC Demote States
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {lcc_demote_state_1_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {lcc_demote_state_2_o*}] -add_delay

# SEP Fuse Sense Done
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports sep_fuse_sense_done_o] -add_delay

# SEP TEST_EN strap (secure test mode request)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports secure_tm_req_i] -add_delay

########################################################
# Child passthrough ports uncovered by the inherited files (flat CDC/RDC)
########################################################
# These SMU ports are 1:1 passthroughs of child ports whose IO delays are
# block-top-gated in the child files. Stamp them here with the same domain
# intent the child uses at its own boundary. Gated on smu_inherit_children
if {$smu_inherit_children} {
    # SEP Adams-Bridge crypto memory read data (memory response inputs, SMUCLK plane)
    set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {abr_mem_rsp_i*}] -add_delay

    # External TRNG interface (SEP stamps SEPCLK; SEPCLK == SMUCLK here)
    set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ext_trng_axil_resp_i*}] -add_delay
    set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMUCLK] [get_ports {ext_trng_axis_req_i*}] -add_delay
    set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_trng_irq_i] -add_delay

    # I3C data/DCT memory read responses (SMC stamps PERIPHERALCLK)
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {i3c_dat_mem_src_i*}] -add_delay
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] [get_ports {i3c_dct_mem_src_i*}] -add_delay

    # SEP external interrupt requests (SEP stamps extintsrc_req* on ck_feedthru)
    set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {sep_ext_interrupts_i*}] -add_delay
}

########################################################
# GPIO pad-ring I/O delays
########################################################
# The SMC pad-ring constraints apply to the same-named SMU ports. The sign-off
# replay (smu_inherit_children) gets them from the inherited SMC constraints;
# a standalone read of this file sources them here.
if {!$smu_inherit_children} {
    source [file normalize $ocah_sdc_dir/../../smc/synth/gpio_io_constraints.sdc]
}

########################################################
# CDC max_delay bounds
########################################################
# Layer 2 of the synthesis CDC constraints: a per-instance bound on every
# synchronizer and async FIFO, tighter than the inter-group default that
# cdc_apply_async_groups applies in the bounded synth scenario. Loaded last so
# these exceptions are the ones the tool keeps where both apply, and so the
# primary-input relaxation at the end sees every constrained pin. Block top
# only, synth scenario only, and only while ::cdc_bound_crossings is set.
if {[cdc_is_block_top] && $::cdc_scenario eq "synth" && $::cdc_bound_crossings} {
    source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
    source [file join $ocah_sdc_dir smu_cdc_max_delay.tcl]
}
