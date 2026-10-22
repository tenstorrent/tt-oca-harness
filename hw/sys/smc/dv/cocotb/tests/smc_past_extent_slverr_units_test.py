# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Past-extent and last-aperture-word response of the SLVERR-declared units.

Spec sources: smc.rdl ocah_past_extent_resp placements, misc_wrap.rdl ocah_gap_resp,
memmap.adoc Address Space Organization, memory_map.adoc UART window row,
uart_log_engine_wrap.adoc, uart_16550 and log_engine memmap.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_past_extent_slverr_units_test_seq import (
    smc_past_extent_slverr_units_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: reset unit 7, eFuse 14, timer 7, base config 10, fabric arrays 35,
# spare wrapper 25, peripherals 4 x 7 + UART and I3C 2 x 2, CLA 3, UART/log-engine wrappers 36.
STIMULUS_FLOOR = 169
# The UART and I3C aperture-end reads bypass the driver, so the scoreboard sees the rest.
UNCONVERTED_READS = 2
SCOREBOARD_ACCESSES = STIMULUS_FLOOR - UNCONVERTED_READS


@pyuvm.test()
class smc_past_extent_slverr_units_test(smc_base_test):
    """Exact DECERR and 0xBADCAB1E past the extent of the SLVERR-declared units and UART wrappers."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PAST-EXTENT-BASE-CONFIG",
        "CHK-PAST-EXTENT-CLA",
        "CHK-PAST-EXTENT-EFUSE",
        "CHK-PAST-EXTENT-FABRIC-CTRL",
        "CHK-PAST-EXTENT-PERIPH",
        "CHK-PAST-EXTENT-RESET-UNIT",
        "CHK-PAST-EXTENT-SPARE",
        "CHK-PAST-EXTENT-TIMER",
        "CHK-PAST-EXTENT-UARTWRAP",
        "CHK-PAST-EXTENT-UARTWRAP-LIVE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_past_extent_slverr_units_test_seq("past_extent_slverr_units_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.unconverted_reads == UNCONVERTED_READS, (
            f"{seq.unconverted_reads} unconverted reads, want {UNCONVERTED_READS}"
        )
        seq.assert_all_reachable(SCOREBOARD_ACCESSES, "PAST_EXTENT_SLVERR_UNITS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
