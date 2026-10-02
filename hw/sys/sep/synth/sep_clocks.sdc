# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
#-----------------------------------------------------------------------------
# SEP clock stampings.
#
# Shared with the closed block flow, which sources this file directly rather
# than keeping its own copy. Reads $clock_periods(...); the sourcing flow
# populates that array first.
#
# The entropy ripple-divider tree is built from the RTL hierarchy and is
# skipped when entropy_source is blackboxed, so it lives in
# sep_entropy_clocks.sdc and is stamped by the open flow alone.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "sep_clocks.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

# Hierarchy-reusable: boundary constraints (create_clock on ports) apply at block top
# only. Replayed under a parent (SMU) these nets carry the parent's clocks, mapped via
# ::cdc_clock_alias, while the memory-interface clocks survive at both levels because
# the parent exports the same-named ports. Identity when no parent has opted in.
if {[info procs cdc_is_block_top] eq ""} {
    source [file normalize [file join [file dirname [info script]] \
        ../../../../flows/synth/constraints/hier_reuse_procs.tcl]]
}
if {[cdc_is_block_top]} {
    create_clock -add -name SEPCLK            -period $clock_periods(SYSCLK_PERIOD)                [get_ports "clk_i"]
    # Free-running reference clock for the system CSR reference counter, which
    # crosses to it from SEPCLK through a synchronizer and an async FIFO.
    create_clock -add -name REFCLK            -period $clock_periods(REFCLK_PERIOD)                [get_ports "clk_ref_i"]
    create_clock -add -name WDTCLK            -period $clock_periods(WDTCLK_PERIOD)                [get_ports "clk_wdt_i"]
    create_clock -add -name JTAG_TCK          -period $clock_periods(JTAG_TCK_PERIOD)              [get_ports "jtag_tck_i"]
}

# OTBN PKA and CPU TCM (ICCM/DCCM) memories (have clock output in request struct).
# Level-independent: the master maps through cdc_clk and the source is the block clock
# port at SEP top, or the u_sep/clk_i instance pin under a parent.
create_generated_clock [get_ports sep_crypto_pka_imem_sram_req_o*clk] -name SEPCLK_PKA_IMEM -master_clock [cdc_clk SEPCLK] -divide_by 1 -source [cdc_port_or_pin "clk_i"] -combinational
create_generated_clock [get_ports sep_crypto_pka_dmem_sram_req_o*clk] -name SEPCLK_PKA_DMEM -master_clock [cdc_clk SEPCLK] -divide_by 1 -source [cdc_port_or_pin "clk_i"] -combinational
create_generated_clock [get_ports sep_cpu_tcm_req_o*clk]              -name SEPCLK_CPU_TCM  -master_clock [cdc_clk SEPCLK] -divide_by 1 -source [cdc_port_or_pin "clk_i"] -combinational

# feedthrough clock for any async input/outputs
if {[cdc_is_block_top]} {
    create_clock -add -name ck_feedthru -period $clock_periods(ck_feedthru_PERIOD)
}

# External sample clock. Present on the SEP port whether or not the entropy
# source is elaborated.
create_clock -add -name ENTROPY_ROSC_CLK -period $clock_periods(ENTROPY_ROSC_PERIOD) \
    [get_ports "entropy_rosc_sample_clk_i"]
