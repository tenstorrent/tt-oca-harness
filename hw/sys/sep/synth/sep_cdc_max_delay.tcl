# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# sep_cdc_max_delay.tcl - SEP CDC max_delay constraints
#
# The per-instance calls live in sep_cdc_max_delay_generated.tcl, enumerated
# offline from the elaborated design. This file holds only what a human decides:
# overrides, exclusions, and notes.
#
# Sourced from constraints.sdc in this directory, after the clock stampings and
# set_async_clock_groups. See "CDC Timing Constraints" in the Integrator Guide.
################################################################################

# SEPCLK, REFCLK and WDTCLK are all create_clock, so their periods read back off
# the clock objects - no ::cdc_clock_period entries needed here. SEPCLK_PKA_IMEM
# and SEPCLK_PKA_DMEM are generated, but no CDC element is clocked by them.

source [file join $ocah_sdc_dir sep_cdc_max_delay_generated.tcl]

################################################################################
# OVERRIDES
################################################################################
# Every proc takes an optional trailing delay in ps that replaces the computed
# value, for the cases where 0.5 * T_dst or 1.0 * T_dst will not close:
#
#   set_cdc_max_delay_prim_reg_cdc <path> SEPCLK WDTCLK 2000
#
# Re-stating a call here after the source above wins, since the later exception
# is the one the tool keeps for identical object specifications. Empty is the
# expected steady state; each entry needs a reason.

# TCK to SEPCLK. The generated enumeration does not list these instances.
set_cdc_max_delay_prim_sync2 u_sep_reset_ctrl/u_jtag_ip_ovrd_sync SEPCLK
set_cdc_max_delay_prim_sync2 u_sep_reset_ctrl/u_jtag_ip_val_sync SEPCLK

################################################################################
cdc_max_delay_summary
