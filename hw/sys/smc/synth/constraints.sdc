# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#-----------------------------------------------------------------------------
# SMC (System Management Controller) block-level timing constraints.
#
# Clocks, generated clocks, clock groups, and I/O delays for every `smc`
# top-level port (hw/sys/smc/rtl/smc.sv) and the AVS clock-mux/divider
# hierarchy (hw/ip/avsbus_controller/rtl/avsbus_controller.sv). GPIO pad-ring
# I/O delays come from gpio_io_constraints.sdc beside this file.
#
# Read by synthesis as the block SDC, by the CDC/RDC sign-off run through
# cdc/smc.cdc_rdc.tcl, and by any parent that replays this block under a
# hierarchy prefix (hw/sys/smu). Clock periods come from
# flows/synth/constraints/clock_periods.tcl; the hooks from cdc_hier_procs.tcl.
#
# Hierarchy-reusable: boundary constraints (create_clock on ports, IO delays,
# clock groups) apply at block top only; the internal generated clocks (the
# AVS clock tree) re-anchor through cdc_inst.
#
# Caveats, called out explicitly:
#   - `rst_primary_periph_clk_no` is a real `smc` top-level port; its I/O
#     delay below is modeled on its sibling reset outputs.
#   - CDC crossings are bounded in two layers. `cdc_apply_async_groups` below
#     declares the asynchronous groups; in the synth scenario it goes through
#     `set_async_clock_groups`, which adds `-allow_paths` and a loose default
#     max_delay per inter-group clock pair, and `smc_cdc_max_delay.tcl`,
#     sourced at the end, tightens each synchronizer and async FIFO
#     individually. The `-allow_paths` is not optional: `set_false_path`
#     outranks `set_max_delay` in exception priority, so a bare
#     `set_clock_groups -asynchronous` would silently mask every per-instance
#     bound. The functional (sign-off) scenario emits the bare form and skips
#     the bounds.
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

# Directory holding this file, so the shared collateral below resolves regardless
# of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
if {[info script] ne ""} {
    set ocah_sdc_dir [file dirname [file normalize [info script]]]
} elseif {[info exists ::env(GIT_ROOT)]} {
    set ocah_sdc_dir [file normalize $::env(GIT_ROOT)/hw/sys/smc/synth]
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


##################
# CLOCK STAMPINGS
##################

# Boundary clocks: block-top only. At the parent these nets carry the parent's clocks
# (SMCCLK -> SMUCLK etc. via ::cdc_clock_alias).
if {[cdc_is_block_top]} {
create_clock -add -name REFCLK                  -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name SMCCLK                  -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_smc_i"]
create_clock -add -name PERIPHERALCLK           -period $clock_periods(PERIPHERALCLK_PERIOD)         [get_ports "clk_periph_i"]
create_clock -add -name TELEMETRYCLK            -period $clock_periods(TELEMETRYCLK_PERIOD)          [get_ports "clk_telemetry_i"]
create_clock -add -name JTAG_TCK                -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "smc_cpu_jtag_TCK_i"]
}

# Memory-interface output clocks: block-top only. The parent stamps its own identically
# shaped generated clocks on its own exported memory ports (smu.clock_defines.tcl).
if {[cdc_is_block_top]} {
# memories
create_generated_clock [get_ports smc_rom_intf_req_o*clk] -name SMCCLK_ROM -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

# Scratch RAM clocks
set scratch_ram_clk_ports [lsort -dictionary [get_object_name [get_ports {smc_scratch_ram_intf_req_o*clk}]]]
set scratch_ram_clk_idx 0
foreach scratch_ram_clk_port $scratch_ram_clk_ports {
    create_generated_clock [get_ports $scratch_ram_clk_port] -name SMCCLK_RAM${scratch_ram_clk_idx} -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
    incr scratch_ram_clk_idx
}

create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*0*clk]  -name SMCCLK_ICACHE_TAG0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*1*clk]  -name SMCCLK_ICACHE_TAG1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*2*clk]  -name SMCCLK_ICACHE_TAG2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_tag_intf_req_o*3*clk]  -name SMCCLK_ICACHE_TAG3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*0*clk]  -name SMCCLK_ICACHE_DATA0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*1*clk]  -name SMCCLK_ICACHE_DATA1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*2*clk]  -name SMCCLK_ICACHE_DATA2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*3*clk]  -name SMCCLK_ICACHE_DATA3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*4*clk]  -name SMCCLK_ICACHE_DATA4  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*5*clk]  -name SMCCLK_ICACHE_DATA5  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*6*clk]  -name SMCCLK_ICACHE_DATA6  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_icache_data_intf_req_o*7*clk]  -name SMCCLK_ICACHE_DATA7  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*0*clk]  -name SMCCLK_DCACHE_TAG0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*1*clk]  -name SMCCLK_DCACHE_TAG1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*2*clk]  -name SMCCLK_DCACHE_TAG2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_tag_intf_req_o*3*clk]  -name SMCCLK_DCACHE_TAG3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational

create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*0*clk]  -name SMCCLK_DCACHE_DATA0  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*1*clk]  -name SMCCLK_DCACHE_DATA1  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*2*clk]  -name SMCCLK_DCACHE_DATA2  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
create_generated_clock [get_ports smc_l1_dcache_data_intf_req_o*3*clk]  -name SMCCLK_DCACHE_DATA3  -master_clock SMCCLK -divide_by 1 -source [get_ports "clk_smc_i"] -combinational
}


# ----------------------
# AVS Clock Constraints
# ----------------------
# Note: For STA you need to care about the divided value (it is a programmable clock divider), but for CDC setup the fact its a divided value is all that matters
set avs_hier [cdc_inst u_smc_peripherals/u_avsbus_controller]

# Stamp each source's generated clock on its gater output
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 1 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk0_gate/clk_o"]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 1 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk1_gate/clk_o"]

# Raw primaries stop at their gater outputs before the OR
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk0_gate/clk_o"] \
    -clocks {REFCLK}
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_refclk_apbclk_mux/u_clk1_gate/clk_o"] \
    -clocks {PERIPHERALCLK}

# Now the clock mux output is fed into a clock divider.
# For SpyGlass CDC setup, the exact divide ratio is less important than the
# source-clock relationship, so the fixed `/4` is acceptable here.
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
    -divide_by 4 \
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
    -divide_by 4 \
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

# CDC-only modeling: collapse the AVS-clock domain attribution downstream of
# the programmable divider. Inside `prim_prog_clk_div_posedge`, the bypass
# path (`u_postdiv_mux/clk0_i`) lets `AVS_CLKMUX_OUTPUT_*` propagate through to
# `clk_o`, while the divided path stamps `AVS_CLK_FROM_*` at `u_div_clk_stdbuf/y_o`. The
# net result is every downstream AVS-domain flop is attributed FOUR clocks
# (mux-out + divided, each from REFCLK and PERIPHERALCLK roots), which the
# tool reports as multi-domain convergence at `interrupt_o`,
# `R_avs_interrupt_F_*`, `readback_data_var[*]`, etc., and as MULTI_SYNC for
# the APB-clock reset that fans into `u_clear_*_resync` handshake blocks.
#
# For CDC, the bypass and divided modes are functionally the SAME AVS clock
# (just different frequencies), so we stop the upstream `AVS_CLKMUX_OUTPUT_*`
# clocks at the post-divider mux output. Downstream AVS-domain flops then
# see only `AVS_CLK_FROM_REFCLK` / `AVS_CLK_FROM_PERIPHERALCLK`, which are
# already declared `-logically_exclusive` below (only one source-mode is
# active at a time).
set_clock_sense -stop_propagation \
    [get_pins "${avs_hier}/u_clk_div/u_postdiv_mux/clk_o"] \
    -clocks {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK}

# Check about these being in the same group
# These two can never be active simultaneously (muxed sources)
set_clock_groups -logically_exclusive \
    -group {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO} \
    -group {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}

# SPI
# SPICLK has no parent-level equivalent (at SMU, spi_clk_i is driven internally by SEP's
# sep_io_spi_req.sck), so it is created at BOTH levels: on the port at block top, on the
# u_smc/spi_clk_i instance pin at the parent. The GPIO pad stampings target ports that
# keep the same names at the SMU top.
create_clock -add -name SPICLK            -period $clock_periods(SPICLK_PERIOD)                [cdc_port_or_pin "spi_clk_i"]

create_generated_clock [get_ports "pad2core_i[9]"] -name SPICLK_IN_GPIO  -master_clock SPICLK -divide_by 1 -source [cdc_port_or_pin "spi_clk_i"]
create_generated_clock [get_ports "core2pad_o[9]"] -name SPICLK_OUT_GPIO -master_clock SPICLK -divide_by 1 -source [cdc_port_or_pin "spi_clk_i"]

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
if {[cdc_is_block_top]} {
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)
}

# Async-domain membership: register the SMC-defined generated clocks into their canonical
# domains (registrations survive at the parent, where the domain name maps through
# ::cdc_clock_alias), then apply the block's own grouping only at block top. The parent
# emits ONE merged set_clock_groups after sourcing every child (cdc_apply_async_groups).
cdc_group_extra REFCLK {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLK_FROM_REFCLK AVS_CLK_DIV_CLK_O_FROM_REFCLK AVS_DIV_TOGGLE_FROM_REFCLK AVS_DIV_CLK_Q_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO AVS_CLK_FROM_REFCLK_GPIO}
cdc_group_extra PERIPHERALCLK {AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK AVS_CLK_FROM_PERIPHERALCLK AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK AVS_DIV_TOGGLE_FROM_PERIPHERALCLK AVS_DIV_CLK_Q_FROM_PERIPHERALCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO AVS_CLK_FROM_PERIPHERALCLK_GPIO}
cdc_group_extra SPICLK {SPICLK_IN_GPIO SPICLK_OUT_GPIO}

# Memory-interface generated clocks (SMCCLK_ROM / SMCCLK_RAM* / SMCCLK_ICACHE_* /
# SMCCLK_DCACHE_*) are all -divide_by 1 -combinational copies of SMCCLK and belong
# in its group; without this every one raises SETUP_CLOCK_GROUP_MISSING. Collected
# by name glob so the scratch-RAM loop count stays in one place (block-top only:
# the create_generated_clock stamps above are block-top gated too).
if {[cdc_is_block_top]} {
    set _smc_mem_gen_clks [list]
    foreach_in_collection c [get_clocks SMCCLK_* -quiet] {
        lappend _smc_mem_gen_clks [get_object_name $c]
    }
    if {[llength $_smc_mem_gen_clks] > 0} {
        cdc_group_extra SMCCLK $_smc_mem_gen_clks
        puts "INFO: grouped [llength $_smc_mem_gen_clks] SMCCLK_* memory generated clocks with SMCCLK"
    }
    unset -nocomplain _smc_mem_gen_clks
}

if {[cdc_is_block_top]} {
    cdc_apply_async_groups {REFCLK SMCCLK PERIPHERALCLK SPICLK TELEMETRYCLK JTAG_TCK ck_feedthru}
}


########################################################
# Input and Output delays
########################################################
# Block-top only: IO delays anchor the block's own ports; at the parent these are internal
# nets whose launch/capture domains come from the real fabric.
if {[cdc_is_block_top]} {

# GPIO input and output delays
# -> handled in gpio_io_constraints.sdc, sourced at the end of this file

# resets
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports powergood_i] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports powergood_stable_o] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cold_ni] -add_delay
set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_cold_stable_ref_clk_no] -add_delay

set_output_delay [expr $clock_periods(REFCLK_PERIOD)*0.5]       -clock [get_clock REFCLK] [get_ports rst_primary_ref_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports rst_primary_smc_clk_no] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports rst_wdt_smc_clk_no] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports rst_cool_n_from_pin_i] -add_delay

# AXI / AXI-Lite interfaces
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sys_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sys_axi_in_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {jtag_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {jtag_axi_in_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_smc_otp_jtag_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_smc_otp_jtag_resp_o*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sep_axi_in_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sep_axi_in_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {output_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {output_axi_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_dtp_csr_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {axil_dtp_csr_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_external_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_external_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {efuse_shim_command_resp_i*}] -add_delay

# telemetry
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports rst_telemetry_ni] -add_delay

set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atdata_i*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atready_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_atvalid_i*}] -add_delay
set_output_delay [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afvalid_o*}] -add_delay
set_input_delay  [expr $clock_periods(TELEMETRYCLK_PERIOD)*0.5] -clock [get_clock TELEMETRYCLK] [get_ports {telemetry_afready_i*}] -add_delay

# WDT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_wdt_first_timeout_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_wdt_second_timeout_o] -add_delay

# interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ext_interrupts_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {sep_mailbox_interrupts_i*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports sep_wdt_reset_n_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_ext_mailbox_interrupts_o*}] -add_delay

# efuse
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {shadow_regs_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_fuse_sense_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_fuse_reset_n_delayed_o] -add_delay

# boot stall
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports boot_stall_jtag_ovrd_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports boot_stall_jtag_val_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports boot_stall_combined_o] -add_delay

# DFT
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports skip_mem_repair_o] -add_delay
# ext_boot_seq_done_i: pinned by smc_case_analysis.tcl in the functional scenario
cdc_pinned_port_delay set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# LC
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {lc_state_i*}] -add_delay

# RAS
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_cluster_ded_o] -add_delay

# NDM
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {smc_ndmreset_request_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_ndmreset_process_o*}] -add_delay

# reset unit
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cfg_flr_pf_active_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {isolate_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ss_reset_complete_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {ss_config_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {ss_reset_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports sync_irq_o] -add_delay

# memory
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_rom_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SMCCLK] [get_ports {smc_rom_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_scratch_ram_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_scratch_ram_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_icache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_icache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_icache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_icache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_dcache_tag_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_dcache_tag_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [filter_collection [get_ports {smc_l1_dcache_data_intf_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_l1_dcache_data_intf_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SMCCLK] [get_ports {trace_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {trace_mem_resp_i*}] -add_delay

# OCTS
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports chiplet_is_primary_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {timer_count_o*}] -add_delay

# DFD
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports xtrigger_ss_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports xtrigger_ss_o] -add_delay

set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_debug_bus_i] -add_delay

# Test (pinned by smc_case_analysis.tcl in the functional scenario)
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay


# DFT
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mem_repair_done_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mem_repair_success_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mem_repair_abort_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mbist_done_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mbist_pass_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mbist_abort_i] -add_delay

# SPI signals below are more relaxed that the typical 50% delay because they just pass through SMC

# SPI enable (controlled by internal registers)
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.4]       -clock [get_clock SMCCLK] [get_ports spi_enable_i] -add_delay

# SPI data and pad control signals
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_txd_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_cs_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_clk_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_clk_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_dqs_ie_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_dqs_oe_n_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_dq_ie_n_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_dq_oe_n_i*}] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_oepad_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_opad_i] -add_delay
set_input_delay  [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_iepad_i] -add_delay
set_output_delay [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports {spi_rxd_o*}] -add_delay
set_output_delay [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_rxds_o] -add_delay
set_output_delay [expr $clock_periods(SPICLK_PERIOD)*0.4]       -clock [get_clock SPICLK] [get_ports spi_mem_rebar_ipad_o] -add_delay

# I3C — data-memory read response bus (struct-flattened port names). Tied or driven
# from the memory controller in chip context; stamp PERIPHERALCLK for block CDC SETUP.
set i3c_dmem_ports [get_ports -quiet "i3c_dat_mem_src_i*"]
if {[sizeof_collection $i3c_dmem_ports] > 0} {
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dmem_ports -add_delay
    puts "INFO: set_input_delay PERIPHERALCLK on i3c_dat_mem_src_i* ([sizeof_collection $i3c_dmem_ports] ports)"
}

set i3c_dct_mem_ports [get_ports -quiet "i3c_dct_mem_src_i*"]
if {[sizeof_collection $i3c_dct_mem_ports] > 0} {
    set_input_delay  [expr $clock_periods(PERIPHERALCLK_PERIOD)*0.5] -clock [get_clock PERIPHERALCLK] $i3c_dct_mem_ports -add_delay
    puts "INFO: set_input_delay PERIPHERALCLK on i3c_dct_mem_src_i* ([sizeof_collection $i3c_dct_mem_ports] ports)"
}

# SMC control/status signals
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_global_base_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {smc_region_size_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports smc_init_mem_done_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports {cla_ext_action_custom_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports tdr_dbg_ctrl_clocks_stopped_by_cla_o] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SMCCLK] [get_ports sep_security_disable_i] -add_delay

# For us its driven by captured straps | shadow reg, but for an adoptor its hard to say. Should not assume anything about the source of this signal.
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports smc_disable_sram_auto_init_i] -add_delay
# tdr_dbg_ctrl_clock_stop_en_i is pinned to 0 in smc_case_analysis.tcl.

set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TMS_i}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TDI_i}] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_TDO_data_o}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_reset_i}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_mfr_id_i*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_part_number_i*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {smc_cpu_jtag_version_i*}] -add_delay

# jtag_reset_ctrl_i.{val,ovrd}*: pinned by smc_case_analysis.tcl in the functional scenario
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_reset_ctrl_i.val*}] -add_delay
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_reset_ctrl_i.ovrd*}] -add_delay

}
# end "if {[cdc_is_block_top]}"

########################################################
# GPIO pad-ring I/O delays
########################################################
# SMC ports, also exported unchanged by SMU, so the replayed SMC constraints
# constrain them at the SMU top as well.
source [file join $ocah_sdc_dir gpio_io_constraints.sdc]

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
    source [file join $ocah_sdc_dir smc_cdc_max_delay.tcl]
}
