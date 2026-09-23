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
# Only the clocks that exist on every flow belong here. The entropy ring
# oscillator's internal clock tree is hierarchy- and library-specific, so it
# lives in sep_entropy_clocks.sdc and is stamped by the open flow alone.
#-----------------------------------------------------------------------------

if {![array exists ::clock_periods]} {
    error "sep_clocks.sdc: clock_periods() is empty; source the flow's clock-period definitions first"
}

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

# entropy_source ring-oscillator sample clock. Non-functional while
# entropy_source is blackboxed, but a top-level port on every flow.
create_clock -add -name ENTROPY_ROSC_CLK  -period $clock_periods(ENTROPY_ROSC_PERIOD) [get_ports "entropy_rosc_sample_clk_i"]
