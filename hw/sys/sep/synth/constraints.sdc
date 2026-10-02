# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#-----------------------------------------------------------------------------
# SEP (Security Processor) block-level timing constraints.
#
# Clocks, generated clocks, and I/O delays for the `sep` top-level port list
# (hw/sys/sep/rtl/sep.sv).
#
# Read by synthesis as the block SDC, by the CDC/RDC sign-off run through
# cdc/sep.cdc_rdc.tcl, and by any parent that replays this block under a
# hierarchy prefix (hw/sys/smu). Clock periods come from
# flows/synth/constraints/clock_periods.tcl; the hooks from cdc_hier_procs.tcl.
#
# Hierarchy-reusable: boundary constraints (create_clock on ports, IO delays,
# clock groups) apply at block top only -- at the SMU top these nets carry
# SMU's clocks (SEPCLK -> SMUCLK, WDTCLK -> SEP_WDT_CLK via ::cdc_clock_alias).
# The PKA memory clocks and ENTROPY_ROSC_CLK survive at both levels: their port
# globs match SMU's same-named exported ports.
#
# Caveats, called out explicitly:
#   - The entropy ripple-divider clocks are commented out while
#     `entropy_source` is blackboxed; the section is kept for when it is
#     elaborated again.
#   - CDC crossings are bounded in two layers. `cdc_apply_async_groups` below
#     declares the asynchronous groups; in the synth scenario it goes through
#     `set_async_clock_groups`, which adds `-allow_paths` and a loose default
#     max_delay per inter-group clock pair, and `sep_cdc_max_delay.tcl`,
#     sourced at the end, tightens each synchronizer and async FIFO
#     individually. The `-allow_paths` is not optional: `set_false_path`
#     outranks `set_max_delay` in exception priority, so a bare
#     `set_clock_groups -asynchronous` would silently mask every per-instance
#     bound. The functional (sign-off) scenario emits the bare form and skips
#     the bounds.
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

# Directory holding this file, so the shared collateral below resolves regardless
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

# Clock periods and the hierarchy-reuse hooks every constraint below goes through.
source [file join $ocah_flow_constraints_dir clock_periods.tcl]
if {[info procs cdc_is_block_top] eq ""} {
    source [file join $ocah_flow_constraints_dir cdc_hier_procs.tcl]
}

# The two entropy sample-clock families are related -logically_exclusive where
# they mux; keep that pair out of the asynchronous declaration in the synth
# scenario (a pair cannot carry both relationships).
set ::cdc_async_exclude {{ENTROPY_*ROSC* ENTROPY_*SHARED_RO*}}


##################
# CLOCK STAMPINGS
##################

if {[cdc_is_block_top]} {
create_clock -add -name SEPCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_i"]
create_clock -add -name REFCLK            -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
create_clock -add -name WDTCLK            -period $clock_periods(WDTCLK_PERIOD)                [get_ports "clk_wdt_i"]
create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_tck_i"]
}

# OTBN PKA and CPU TCM (ICCM/DCCM) memories (have clock output in request struct)
# Level-independent: the master maps through cdc_clk (SEPCLK -> SMUCLK) and the source is
# the block clock port (SEP top) or the u_sep/clk_i instance pin (SMU top).
create_generated_clock [get_ports sep_crypto_pka_imem_sram_req_o*clk] -name SEPCLK_PKA_IMEM -master_clock [cdc_clk SEPCLK] -divide_by 1 -source [cdc_port_or_pin "clk_i"] -combinational
create_generated_clock [get_ports sep_crypto_pka_dmem_sram_req_o*clk] -name SEPCLK_PKA_DMEM -master_clock [cdc_clk SEPCLK] -divide_by 1 -source [cdc_port_or_pin "clk_i"] -combinational
create_generated_clock [get_ports sep_cpu_tcm_req_o*clk]              -name SEPCLK_CPU_TCM  -master_clock [cdc_clk SEPCLK] -divide_by 1 -source [cdc_port_or_pin "clk_i"] -combinational

# feedthrough clock for any async input/outputs
if {[cdc_is_block_top]} {
create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)
}

# # Entropy clocks below are non-functional; entropy_source is currently blackboxed.

# # entropy_source sample-clock tree (egen/sclk): a length-109 shared ring oscillator
# # plus one 5-stage ripple divider per generator. Each divider is fed by a mux between
# # the external sample clock (ENTROPY_ROSC_CLK) and the shared RO, so every divider tap
# # acts as a clock and is declared from both sources. Divide ratio is immaterial for
# # CDC; only the source-clock relationship matters.
# # shared ring oscillator output buffer pin
# set entropy_shared_ro_pin [get_pins "u_sep_crypto/u_sep_trng/u_entropy_source_s3c_scan/egen/sclk/shared_ro/fbf/z_o"]

# # entropy_source ring-oscillator sample clock
# (level-independent: SMU exports the same-named entropy_rosc_sample_clk_i port)
create_clock -add -name ENTROPY_ROSC_CLK  -period $clock_periods(ENTROPY_ROSC_PERIOD) [get_ports "entropy_rosc_sample_clk_i"]

# # entropy_source internal shared ring-oscillator clock
# create_clock -add -name ENTROPY_SHARED_RO -period $clock_periods(ENTROPY_SHARED_RO_PERIOD) $entropy_shared_ro_pin

# # all toggle-flop cells once; each divider's taps are selected by path below
# set entropy_gdffqb [lsort -dictionary [get_object_name [get_cells -hierarchical -filter "ref_name == gdffqb"]]]

# # one generated clock per divider tap from each source, numbered in stamping order
# set entropy_tap_idx 0
# foreach entropy_tap_cell [lsearch -all -inline -glob $entropy_gdffqb {*egen/sclk/gen_ecmplx*u_sample_clk_divider*u_div_ff}] {
#     set entropy_tap_pin [get_pins "${entropy_tap_cell}/q_o/Q"]
#     create_generated_clock -add -name ENTROPY_SCLK_FROM_ROSC_${entropy_tap_idx}      -master_clock ENTROPY_ROSC_CLK  -divide_by 2 -source [get_ports "entropy_rosc_sample_clk_i"] $entropy_tap_pin
#     create_generated_clock -add -name ENTROPY_SCLK_FROM_SHARED_RO_${entropy_tap_idx} -master_clock ENTROPY_SHARED_RO -divide_by 2 -source $entropy_shared_ro_pin $entropy_tap_pin
#     incr entropy_tap_idx
# }

# # debug monitor ripple divider (dbg/u_ripple_divider): observability only -- it divides a
# # debug-selected internal signal off-chip via signal_monitor_o, never into functional logic.
# # The source is a dynamic debug mux, so declare each tap as its own clock and keep the whole
# # divider in one async group, isolated from the functional clocks.
# set entropy_dbg_tap_idx 0
# foreach entropy_dbg_cell [lsearch -all -inline -glob $entropy_gdffqb {*dbg/u_ripple_divider*u_div_ff}] {
#     create_clock -add -name ENTROPY_DBG_MON_${entropy_dbg_tap_idx} -period $clock_periods(ENTROPY_ROSC_PERIOD) [get_pins "${entropy_dbg_cell}/q_o/Q"]
#     incr entropy_dbg_tap_idx
# }

# # the source mux passes the external clock or the shared RO into each divider, never both,
# # so they are exclusive at every mux. Across generators the two families are not strictly
# # exclusive (one generator can run external while another runs shared), but they never
# # converge anywhere outside these muxes, so grouping each master plus its taps as
# # logically_exclusive only suppresses analysis where the two sources actually mux -- safe
# set_clock_groups -logically_exclusive \
#     -group [concat {ENTROPY_ROSC_CLK}  [get_object_name [get_clocks "ENTROPY_SCLK_FROM_ROSC_*"]]] \
#     -group [concat {ENTROPY_SHARED_RO} [get_object_name [get_clocks "ENTROPY_SCLK_FROM_SHARED_RO_*"]]]

# Async-domain membership: register SEP's generated clocks into their canonical domains
# (SEPCLK maps to SMUCLK at the parent); the block applies its own grouping only at block
# top, the parent emits one merged set_clock_groups after sourcing every child.
cdc_group_extra SEPCLK {SEPCLK_PKA_IMEM SEPCLK_PKA_DMEM SEPCLK_CPU_TCM}

if {[cdc_is_block_top]} {
    cdc_apply_async_groups {SEPCLK WDTCLK REFCLK JTAG_TCK ck_feedthru ENTROPY_ROSC_CLK}
    # ENTROPY_* groups intentionally not applied while entropy_source is blackboxed; see above.
}

########################################################
# Input and Output delays
########################################################
# Block-top only: IO delays anchor the block's own ports; at the parent these are internal
# nets whose launch/capture domains come from the real fabric.
if {[cdc_is_block_top]} {

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

# JTAG SEP reset control overrides (TCK domain); pinned by sep_case_analysis.tcl in the
# functional scenario, so the delay applies only where they are not pinned
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.val*}] -add_delay
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports {jtag_sep_reset_ctrl_i.ovrd*}] -add_delay

# Test (pinned in the functional scenario)
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports scan_rst_ni] -add_delay
cdc_pinned_port_delay set_input_delay [expr $clock_periods(JTAG_TCK_PERIOD)*0.5]     -clock [get_clock JTAG_TCK] [get_ports test_en_i] -add_delay

# Boot sequence done (pinned in the functional scenario)
cdc_pinned_port_delay set_input_delay [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports ext_boot_seq_done_i] -add_delay

# DMI interface
# - only SEPCLK because there is no internal synchronization like the mpc or cpu_halt
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_core_enable_i] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_enable_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_en_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_uncore_wr_en_o] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_addr_o*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_wdata_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {dmi_uncore_rdata_i*}] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports dmi_active_o] -add_delay

# CPU trace
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_trace_o*}] -add_delay

# CPU configuration inputs
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {jtag_id_i*}] -add_delay

# Interrupts
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports timer_int_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports soft_int_i] -add_delay
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports {extintsrc_req_i*}] -add_delay

# SEP memories
# set the outputs to lower delay, they should go direct to the memory macro
# set the inputs to higher delay to emulate the access time of the memory
# - ROMs will have a large access time (70%), SRAMs will have a smaller access time (50%)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [remove_from_collection [get_ports {sep_cpu_tcm_req_o*}] [get_ports {sep_cpu_tcm_req_o*clk}]] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_cpu_tcm_rsp_i*}] -add_delay

# Scratchpad SRAM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_sram_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_sram_rsp_i*}] -add_delay

# Boot ROM interface
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {sep_boot_rom_rsp_i*}] -add_delay

# Key Manager memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.7]       -clock [get_clock SEPCLK] [get_ports {km_rom_mem_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_req_o*}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {km_sram_mem_rsp_i*}] -add_delay

# Adams-Bridge crypto memory interface (request out to macros, response data back)
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {abr_mem_req*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {abr_mem_rsp*}] -add_delay

# Crypto PKA memory interfaces
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_imem_sram_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_imem_sram_rsp_i*}] -add_delay

set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.1]       -clock [get_clock SEPCLK] [filter_collection [get_ports {sep_crypto_pka_dmem_sram_req_o*}] {full_name !~ ".*clk.*"}] -add_delay
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {sep_crypto_pka_dmem_sram_rsp_i*}] -add_delay

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
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports security_disable_o] -add_delay

# Mailbox interrupts
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports {smc_mailbox_interrupt_o*}] -add_delay

# Fuse sense status
set_input_delay  [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports smc_fuse_sense_done_i] -add_delay
set_output_delay [expr $clock_periods(SYSCLK_PERIOD)*0.5]       -clock [get_clock SEPCLK] [get_ports sep_fuse_sense_done_o] -add_delay

# TEST_EN strap (secure test mode request)
set_input_delay  [expr $clock_periods(ck_feedthru_PERIOD)*0.5]  -clock [get_clock ck_feedthru] [get_ports secure_tm_req_i] -add_delay

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

}
# end of block-top-only Input and Output delays

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
    source [file join $ocah_sdc_dir sep_cdc_max_delay.tcl]
}
