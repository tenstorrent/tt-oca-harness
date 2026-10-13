# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Past-extent and last-aperture-word response of the SLVERR-declared units.

Contract XBAR_020, anchor smc_past_extent_slverr_units_test.
Allocated scenarios: XBAR-DEC-RESET-UNIT.S3/S4, XBAR-DEC-EFUSE.S3/S4, XBAR-DEC-TIMER.S3/S4,
XBAR-DEC-BASE-CONFIG.S4, XBAR-DEC-FABRIC-CTRL.S3/S4, XBAR-DEC-SPARE.S3/S4, XBAR-DEC-PERIPH.S2-S4,
XBAR-DEC-CLA.S2.
Spec sources: smc.rdl ocah_past_extent_resp placements, misc_wrap.rdl ocah_gap_resp,
memmap.adoc Address Space Organization.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_past_extent_slverr_units_test_seq import (
    smc_past_extent_slverr_units_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: reset unit 7, eFuse 14, timer 7, base config 10, fabric arrays 35,
# spare wrapper 25, peripherals 4 x 7 + UART and I3C 2 x 2, CLA 3.
STIMULUS_FLOOR = 133


@pyuvm.test()
class smc_past_extent_slverr_units_test(smc_base_test):
    """Exact DECERR and 0xBADCAB1E past the extent of the SLVERR-declared units."""

    required_evidence = (
        "CHK-PAST-EXTENT-RESET-UNIT",
        "CHK-PAST-EXTENT-EFUSE",
        "CHK-PAST-EXTENT-TIMER",
        "CHK-PAST-EXTENT-BASE-CONFIG",
        "CHK-PAST-EXTENT-FABRIC-CTRL",
        "CHK-PAST-EXTENT-SPARE",
        "CHK-PAST-EXTENT-PERIPH",
        "CHK-PAST-EXTENT-CLA",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_past_extent_slverr_units_test_seq("past_extent_slverr_units_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "PAST_EXTENT_SLVERR_UNITS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
