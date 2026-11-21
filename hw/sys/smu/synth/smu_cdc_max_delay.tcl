# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# smu_cdc_max_delay.tcl - SMU CDC max_delay constraints
#
# The per-instance calls live in smu_cdc_max_delay_generated.tcl, enumerated
# offline from the elaborated design. This file holds only what a human decides:
# overrides, exclusions, and notes.
#
# Sourced from constraints.sdc in this directory, after the clock stampings and
# set_async_clock_groups. See "CDC Timing Constraints" in the Integrator Guide.
################################################################################

################################################################################
# GENERATED-CLOCK PERIODS
################################################################################
# A generated clock carries no readable `period` attribute, so the periods of the
# AVS clocks have to be stated. Derived from their create_generated_clock in
# constraints.sdc, where divide_by N means N x the master's period. Keep these
# in step with that file.
set ::cdc_clock_period(AVS_CLKMUX_OUTPUT_FROM_REFCLK) \
    $clock_periods(REFCLK_PERIOD)
set ::cdc_clock_period(AVS_CLKMUX_OUTPUT_FROM_PERIPHERALCLK) \
    $clock_periods(PERIPHERALCLK_PERIOD)
set ::cdc_clock_period(AVS_CLK_DIV_CLK_O_FROM_REFCLK) \
    [expr { 2 * $clock_periods(REFCLK_PERIOD) }]
set ::cdc_clock_period(AVS_CLK_DIV_CLK_O_FROM_PERIPHERALCLK) \
    [expr { 4 * $clock_periods(PERIPHERALCLK_PERIOD) }]

source [file join $ocah_sdc_dir smu_cdc_max_delay_generated.tcl]

################################################################################
# JTAG2AXI BRIDGES
################################################################################
# The CDC elements of the tdr2axi bridges, which the generated file does not list:
# the DMI request handshake (JTAG_TCK to SMUCLK), the DMI response handshake
# (SMUCLK to JTAG_TCK) and the reset synchronizer of each clock domain.
foreach _bridge {
    gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi/gen_axi_lite.u_tdr2axi
    gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi/gen_axi_lite.u_tdr2axi
    gen_smc_jtag2axi.u_smc_jtag2axi/gen_axi.u_tdr2axi
} {
    set _inst u_dtp/u_jtag_intf_unit/u_jtag_ptap/$_bridge
    set_cdc_max_delay_cdc_2phase_clearable $_inst/u_dmi_tdr_bridge/u_cdc_req JTAG_TCK SMUCLK
    set_cdc_max_delay_cdc_2phase_clearable $_inst/u_dmi_tdr_bridge/u_cdc_resp SMUCLK JTAG_TCK
    set_cdc_max_delay_prim_sync_reset $_inst/u_rst_clk_sync/u_sync_reset SMUCLK
    set_cdc_max_delay_prim_sync_reset $_inst/u_rst_tck_sync/u_sync_reset JTAG_TCK
}
unset -nocomplain _bridge _inst

################################################################################
# OVERRIDES
################################################################################
# Every proc takes an optional trailing delay in ps that replaces the computed
# value, for the cases where 0.5 * T_dst or 1.0 * T_dst will not close:
#
#   set_cdc_max_delay_axi_cdc <path> PERIPHERALCLK SMUCLK 2000
#
# Re-stating a call here after the source above wins, since the later exception
# is the one the tool keeps for identical object specifications. Empty is the
# expected steady state; each entry needs a reason.

################################################################################
cdc_max_delay_summary
