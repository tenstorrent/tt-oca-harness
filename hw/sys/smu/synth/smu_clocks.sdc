# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SMU clock stampings.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Reads $clock_periods(...); the sourcing flow
# populates that array first.
#
# `smu_sam_flow` selects whether the SMC/DTP/SEP subcomponents are elaborated
# or replaced by signoff abstract models; the into-hierarchy AVS clock tree
# exists only in the former.
#-----------------------------------------------------------------------------

if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}

if {![array exists ::clock_periods]} {
    error "smu_clocks.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

# smu_sam_flow        -- SMC/DTP/SEP are blackboxed signoff abstract models, so
#                        their RTL is absent and ports they drive are undriven.
# smu_inherit_children -- the run is flat and replays each child's own files
#                        under an instance prefix. The RTL is present, but the
#                        children supply the constraints reaching into it.
if {![info exists smu_sam_flow]}         { set smu_sam_flow 0 }
if {![info exists smu_inherit_children]} { set smu_inherit_children 0 }
set smu_full_hier [expr {!$smu_sam_flow}]
set smu_owns_child_copies [expr {$smu_full_hier && !$smu_inherit_children}]

##################
# CLOCK STAMPINGS
##################

create_clock -add -name REFCLK            -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name SMUCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_smu_i"]
create_clock -add -name PERIPHERALCLK     -period $clock_periods(PERIPHERALCLK_PERIOD)         [get_ports "clk_periph_i"]
create_clock -add -name TELEMETRYCLK      -period $clock_periods(TELEMETRYCLK_PERIOD)          [get_ports "clk_telemetry_i"]
create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_ptap_client_tap_ctrl_i*tck*"]

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

# memories
# The SMC SRAM/cache/ROM interface output clocks are defined and signed off
# INSIDE the SMC block; at the SMU boundary under a SAM (blackboxed) flow they
# would be unconstrained and undriven, so only stamp them when SMC/DTP/SEP RTL
# is fully present.
if {$smu_full_hier} {
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
}

if {$smu_owns_child_copies} {
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

# `set_clock_sense` needs a leaf pin, and every pin on an RTL module boundary is
# hierarchical, so the stops below only apply once technology mapping has turned
# the mux into a library cell. DC reports that failure without raising a Tcl
# error, so an unguarded call fails in silence -- hence the check.
set avs_mux_cell [get_cells -quiet -of_objects \
    [get_pins -quiet "${avs_hier}/u_refclk_apbclk_mux/clk_o"]]
set avs_mapped [expr { [sizeof_collection $avs_mux_cell] \
                       && [get_attribute -quiet $avs_mux_cell is_hierarchical] ne "true" }]

# Tell the tool the raw primaries stop at the mux output — the generated clocks take over from there
if { $avs_mapped } {
    set_clock_sense -stop_propagation \
        [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
        -clocks {REFCLK PERIPHERALCLK}
} else {
    puts "INFO: smu_clocks: the clock-mux output is still a hierarchical pin; the REFCLK and\
          PERIPHERALCLK clock-sense stops are not applied"
}

# Now the clock mux output is fed into a clock divider.
# Important RTL nuance: `prim_prog_clk_div_posedge` can also bypass the divider
# internally, so `avs_clock_o` may be launched either by the muxed parent clock
# or by the divided clock depending on mode.
# AVS clock when sourced from REFCLK (modes 10/11, DEFAULT)
create_generated_clock -add -name AVS_CLK_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"]

# AVS clock when sourced from PERIPHERALCLK (modes 00/01)
create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"]

# Same divided-clock intent on `u_clk_div/clk_o` (`pre_testmux_avs_clk`) so downstream
# STA does not flag an undeclared setup clock when propagation from u_div_clk_buf/clk_o
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

# Internal `div_clk` net (flop -> prim_clock_buf clk_i): stamped so downstream STA can
# resolve the setup clock looking for a PotentialRoot at `div_clk`, matching the
# energy already modeled at y_o.
create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_REFCLK \
    -master_clock REFCLK \
    -divide_by 2 \
    -source [get_ports "clk_ref_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_i"]

create_generated_clock -add -name AVS_DIV_TOGGLE_FROM_PERIPHERALCLK \
    -master_clock PERIPHERALCLK \
    -divide_by 4 \
    -source [get_ports "clk_periph_i"] \
    [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_i"]

# Toggle flop output (feeds u_div_clk_buf and u_postdiv_mux clk1_i). See the
# `div_clk/Q` caveat in the file header: this pin only exists post-synthesis,
# once technology mapping has assigned a concrete cell/pin name to the
# `always_ff`-inferred `div_clk` register in prim_prog_clk_div_posedge.
if { [sizeof_collection [get_pins -quiet "${avs_hier}/u_clk_div/div_clk/Q"]] } {
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
} else {
    puts "INFO: smu_clocks: u_clk_div/div_clk/Q does not exist yet; AVS_DIV_CLK_Q_FROM_REFCLK\
          and AVS_DIV_CLK_Q_FROM_PERIPHERALCLK are not stamped"
}

# apply generated clock to the final gpio output pin as well
create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_REFCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_REFCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLK_FROM_REFCLK_GPIO \
    -master_clock AVS_CLK_FROM_REFCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_refclk_apbclk_mux/clk_o"] \
    [get_ports {core2pad_o[49]}]

create_generated_clock -add -name AVS_CLK_FROM_PERIPHERALCLK_GPIO \
    -master_clock AVS_CLK_FROM_PERIPHERALCLK \
    -divide_by 1 \
    -source [get_pins "${avs_hier}/u_clk_div/u_div_clk_buf/clk_o"] \
    [get_ports {core2pad_o[49]}]

# Downstream AVS flops should resolve against `AVS_CLK_FROM_REFCLK` /
# `AVS_CLK_FROM_PERIPHERALCLK` families, which are `-logically_exclusive` below
# (only one premux source mode is active at a time).
if { $avs_mapped } {
    set_clock_sense -stop_propagation \
        [get_pins "${avs_hier}/u_clk_div/u_postdiv_mux/clk_o"] \
        -clocks {AVS_CLKMUX_OUTPUT_FROM_REFCLK AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK}
} else {
    puts "INFO: smu_clocks: the post-divider mux output is still a hierarchical pin; its\
          clock-sense stop is not applied"
}

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

# Async groups: include the AVS divider clocks only with full hierarchy (synth);
