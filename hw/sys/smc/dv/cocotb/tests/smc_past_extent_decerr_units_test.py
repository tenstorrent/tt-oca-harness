# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Past-extent and last-aperture-word response of the DECERR write units.

Spec sources: smc.rdl ocah_past_extent_resp placements, memmap.adoc Address Space Organization.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_past_extent_decerr_units_test_seq import (
    smc_past_extent_decerr_units_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: 4 single-register units x 7 plus DMA and zeroer x 10 each.
STIMULUS_FLOOR = 48


@pyuvm.test()
class smc_past_extent_decerr_units_test(smc_base_test):
    """Exact DECERR and 0xBADCAB1E past the extent of six DECERR write units."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PAST-EXTENT-CPU-CTRL",
        "CHK-PAST-EXTENT-DFX",
        "CHK-PAST-EXTENT-DMA-ZEROER",
        "CHK-PAST-EXTENT-MAILBOX",
        "CHK-PAST-EXTENT-WDT",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_past_extent_decerr_units_test_seq("past_extent_decerr_units_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "PAST_EXTENT_DECERR_UNITS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
