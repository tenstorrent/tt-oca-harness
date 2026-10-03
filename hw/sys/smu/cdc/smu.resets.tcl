# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
##########
# RESETS (SMU top)
##########
# Boundary truth for the SMU top ports. These deliberately mirror SMC's port resets
# (the ports are 1:1 feedthroughs into u_smc), so the inherited smc.resets.tcl skips its
# own port-reset creation via the identity entries in ::cdc_reset_alias -- each reset
# name is created exactly once, here.

create_reset -name POWERGOOD_RESET_N {"powergood_i"} -async -type reset -value low -disable_assertions_db
create_reset -name COLD_RESET_PAD_N {"rst_cold_ni"} -async -type reset -value low -disable_assertions_db
create_reset -name COOL_RESET_FROM_PIN_N {"rst_cool_n_from_pin_i"} -async -type reset -value low -disable_assertions_db
create_reset -name TELEMETRY_RESET_N {"rst_telemetry_ni"} -both -type reset -value low -disable_assertions_db
create_reset -name SCAN_RESET_N {"scan_rst_ni"} -both -type reset -value low -disable_assertions_db

# No reset->clock assertion sequence from the raw POWERGOOD_RESET_N pad: DTP/SEP flops are
# reset through the SMC powergood stretcher, so coverage is the inherited SMC sequence on
# POWERGOOD_STABLE_N (smc.resets.tcl, clock names aliased) plus the pad->stable reset chain.
