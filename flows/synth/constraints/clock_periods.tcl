# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# clock_periods.tcl - the one table of clock periods every block SDC reads
#
# Units are picoseconds. Each hw/sys/<block>/synth/constraints.sdc sources this
# file before its create_clock calls, so a period changes in one place.
#
# SYSCLK is set to 1000 MHz, above the 800 MHz target, so the major paths are
# closed with margin.
################################################################################

global clock_periods
set clock_periods(REFCLK_PERIOD) 10000
set clock_periods(SYSCLK_PERIOD) 1000
set clock_periods(PERIPHERALCLK_PERIOD) 5000
set clock_periods(SPICLK_PERIOD) 5000
set clock_periods(TELEMETRYCLK_PERIOD) 2000
set clock_periods(JTAG_TCK_PERIOD) 10000
set clock_periods(ck_feedthru_PERIOD) 10000
set clock_periods(WDTCLK_PERIOD) 10000
# Entropy periods below are non-functional; entropy_source is currently blackboxed.
set clock_periods(ENTROPY_ROSC_PERIOD) 2500
set clock_periods(ENTROPY_SHARED_RO_PERIOD) 2300
