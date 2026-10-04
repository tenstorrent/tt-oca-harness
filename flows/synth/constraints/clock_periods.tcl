# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
################################################################################
# clock_periods.tcl - target clock periods, in picoseconds
#
# One table for every block: a block reads the entries it needs and ignores the
# rest, so a period is defined once no matter how many blocks see that clock.
# Sourced by each hw/sys/<block>/synth/constraints.sdc before any file that
# stamps a clock or an I/O delay, and by the closed block flow in place of its
# own copy.
#
# SYSCLK is at 1000MHz, overclocked so that we can solve major paths and meet
# timing at 800MHz.
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
