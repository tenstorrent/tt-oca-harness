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
# This is reference/documentation-level SDC: the current Yosys-based synth
# flow (flows/synth/yosys) drives ABC with a minimal driving-cell/load model
# (tech/ihp-sg13g2/abc.constr) rather than a full SDC. A full SDC like this one
# only becomes a real input once a place-and-route or standalone STA stage
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
#     `set_async_clock_groups` below declares the asynchronous groups with
#     `-allow_paths` and applies a loose default max_delay per inter-group
#     clock pair; `sep_cdc_max_delay.tcl`, sourced at the end, tightens each
#     synchronizer and async FIFO individually. The `-allow_paths` is not
#     optional: `set_false_path` outranks `set_max_delay` in exception
#     priority, so a bare `set_clock_groups -asynchronous` would silently mask
#     every per-instance bound.
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

# Directory holding this file, so the CDC collateral below resolves regardless
# of the invoking tool's working directory. `info script` is the file currently
# being read; GIT_ROOT covers tools that do not set it.
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

# Units are picoseconds.
global clock_periods
set clock_periods(REFCLK_PERIOD)            10000
set clock_periods(SYSCLK_PERIOD)            1000
set clock_periods(PERIPHERALCLK_PERIOD)     5000
set clock_periods(SPICLK_PERIOD)            5000
set clock_periods(TELEMETRYCLK_PERIOD)      2000
set clock_periods(JTAG_TCK_PERIOD)          10000
set clock_periods(ck_feedthru_PERIOD)       10000
set clock_periods(WDTCLK_PERIOD)            10000
# Entropy periods apply when entropy_source is elaborated.
set clock_periods(ENTROPY_ROSC_PERIOD)      2500
set clock_periods(ENTROPY_SHARED_RO_PERIOD) 2300

##################
# CLOCK STAMPINGS
##################

create_clock -add -name SEPCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_i"]
# Free-running reference clock for the system CSR reference counter, which
# crosses to it from SEPCLK through a synchronizer and an async FIFO.
create_clock -add -name REFCLK            -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name WDTCLK            -period $clock_periods(WDTCLK_PERIOD)                [get_ports "clk_wdt_i"]
create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_tck_i"]

# OTBN PKA memories (have clock output in request struct)
create_generated_clock [get_ports sep_crypto_pka_imem_sram_req*clk] -name SEPCLK_PKA_IMEM -master_clock SEPCLK -divide_by 1 -source [get_ports "clk_i"] -combinational
create_generated_clock [get_ports sep_crypto_pka_dmem_sram_req*clk] -name SEPCLK_PKA_DMEM -master_clock SEPCLK -divide_by 1 -source [get_ports "clk_i"] -combinational

# CPU TCM (ICCM/DCCM) memories (have clock output in request struct)
create_generated_clock [get_ports sep_cpu_tcm_req_o*clk] -name SEPCLK_CPU_TCM -master_clock SEPCLK -divide_by 1 -source [get_ports "clk_i"] -combinational

# feedthrough clock for any async input/outputs
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)

# External sample clock. Present on the SEP port whether or not the entropy
# source is elaborated.
create_clock -add -name ENTROPY_ROSC_CLK -period $clock_periods(ENTROPY_ROSC_PERIOD) \
    [get_ports "entropy_rosc_sample_clk_i"]

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

    set entropy_ref_cells [get_cells -hierarchical -quiet -filter "ref_name == prim_dffrxq"]
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

# Asynchronous groups, declared with `-allow_paths` plus a loose default bound
# on every inter-group clock pair. The per-instance bounds sourced at the end of
# this file refine that default; without `-allow_paths` they would be masked.
# The two entropy sample-clock families are already `-logically_exclusive`
# above, so `-exclude` keeps that one pair out of the asynchronous declaration
# -- a clock pair cannot carry both relationships. Groups matching no clock are
# dropped, so the entropy groups cost nothing while `entropy_source` is
# blackboxed.
source [file join $ocah_flow_constraints_dir async_clock_groups.tcl]

set_async_clock_groups {
    {SEPCLK SEPCLK_PKA_IMEM SEPCLK_PKA_DMEM SEPCLK_CPU_TCM}
    {REFCLK}
    {WDTCLK}
    {JTAG_TCK}
    {ENTROPY_ROSC_CLK  ENTROPY_SCLK_FROM_ROSC_*}
    {ENTROPY_SHARED_RO ENTROPY_SCLK_FROM_SHARED_RO_*}
    {ENTROPY_DBG_MON_*}
    {ck_feedthru}
} -exclude {{ENTROPY_*ROSC* ENTROPY_*SHARED_RO*}}


########################################################
# Input and Output delays
########################################################

# resets
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports rst_ni] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dbg_rstb_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports wdt_rst_ni] -add_delay
set_output_delay [expr $clock_periods(WDTCLK_PERIOD)*0.5]       -clock [get_clock WDTCLK] [get_ports wdt_timer_rst_req_o] -add_delay

# JTAG
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tms_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdi_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports jtag_trst_ni] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdo_o] -add_delay
set_output_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports jtag_tdoEn_o] -add_delay

# OTP debug AXI-Lite interface
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axil_sep_otp_jtag_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {axil_sep_otp_jtag_resp_o*}] -add_delay

# MPC debug interface (async)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_debug_halt_req_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_debug_run_req_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports mpc_reset_run_req_i] -add_delay

# CPU halt/run interface (async)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cpu_halt_req_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports cpu_run_req_i] -add_delay

# JTAG SEP reset control overrides (TCK domain)
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.val*}] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.ovrd*}] -add_delay

# Test
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay
set_input_delay  [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay

# Boot sequence done
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# DMI interface
# - only SEPCLK because there is no internal synchronization like the mpc or cpu_halt
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_core_enable] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_enable] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_en] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_wr_en] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_addr*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_wdata*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_rdata*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_active] -add_delay

# CPU trace
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_trace*}] -add_delay

# CPU configuration inputs
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {jtag_id*}] -add_delay

# Interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports timer_int] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports soft_int] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {extintsrc_req*}] -add_delay

# SEP memories
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [remove_from_collection [get_ports {sep_cpu_tcm_req_o*}] [get_ports {sep_cpu_tcm_req_o*clk}]] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_tcm_rsp_i*}] -add_delay

# Scratchpad SRAM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_sram_req*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_sram_rsp*}] -add_delay

# Boot ROM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_req*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_rsp*}] -add_delay

# Key Manager memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_rsp_i*}] -add_delay

# Crypto PKA memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_imem_sram_req*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_imem_sram_rsp*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_dmem_sram_req*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_dmem_sram_rsp*}] -add_delay

# SMN AXI interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_outbound_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_outbound_axi_resp_i*}] -add_delay

set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_inbound_axi_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smn_inbound_axi_resp_o*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_ext_to_smc_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_ext_to_smc_axi_resp_i*}] -add_delay

# External TRNG interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axil_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axil_resp_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axis_req_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {ext_trng_axis_rsp_o*}] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_trng_irq_i] -add_delay

# Key Manager interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports km_unrecoverable_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports km_recoverable_err_o] -add_delay

# Efuse interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_bank_ctrl_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_bank_ctrl_resp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_shim_command_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {efuse_shim_command_resp_i*}] -add_delay

# LC demote state
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lcc_demote_state_1_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lcc_demote_state_2_o*}] -add_delay

# IO interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_io_spi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_io_spi_rsp_i*}] -add_delay

# LC state
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {lc_state_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports lc_sigint_err_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {feat_ctrl_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports security_disable_o] -add_delay

# Mailbox interrupts
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smc_mailbox_interrupt_o*}] -add_delay

# Fuse sense status
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports smc_fuse_sense_done_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports sep_fuse_sense_done_o] -add_delay

# Straps
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {secure_tm_req_i}] -add_delay

# SEP external interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_external_axi_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_external_axi_resp_i*}] -add_delay

# SMC address configuration
# - don't need much delay as it is just a register directly from SMC
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.2]       -clock [get_clock SEPCLK] [get_ports {smc_global_base_addr_i*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.2]       -clock [get_clock SEPCLK] [get_ports {smc_region_size_i*}] -add_delay

# SEP aperture configuration
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_global_base_addr_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_region_size_o*}] -add_delay

# External debug bus
set_output_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {ext_debug_bus_o*}] -add_delay
########################################################
# CDC max_delay bounds
########################################################
# Layer 2: a per-instance bound on every synchronizer and async FIFO, tighter
# than the inter-group default applied by set_async_clock_groups above. Loaded
# last so these exceptions are the ones the tool keeps where both apply, and so
# the primary-input relaxation at the end sees every constrained pin.
source [file join $ocah_flow_constraints_dir cdc_max_delay_procs.tcl]
source [file join $ocah_sdc_dir sep_cdc_max_delay.tcl]
