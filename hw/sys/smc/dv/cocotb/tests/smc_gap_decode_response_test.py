# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gap, SLVERR-window and debug-module aperture responses on the three inbound ports.

Spec sources: memmap.adoc Address Space Organization, smc.rdl ocah_gap_resp / ocah_hole_resp /
ocah_past_extent_resp placements, smc_mailbox placement.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gap_decode_response_test_seq import smc_gap_decode_response_test_seq
from smc_base_test import smc_base_test

# Accesses the sequence issues: setup 4, sep@LOCAL gap words 2 + 2 + 4, five other port/base
# gap legs 5 x 8, window 4 + neighbours 4 + five other window legs 5 x 4, debug 6 x 6, restore 6.
STIMULUS_FLOOR = 122


@pyuvm.test()
class smc_gap_decode_response_test(smc_base_test):
    """DECERR gap reads and writes, observed SLVERR-window writes and debug-aperture DECERR."""

    required_evidence = (
        "CHK-GAP-READ-DECERR",
        "CHK-GAP-WRITE-DECERR",
        "CHK-GAP-ZEROER-CPU-DECERR",
        "CHK-GAP-PORT-BASE-MATRIX",
        "CHK-SLVERR-WINDOW-WRITE-FIRST",
        "CHK-SLVERR-WINDOW-WRITE-LAST",
        "CHK-SLVERR-WINDOW-READ",
        "CHK-SLVERR-WINDOW-NEIGHBOURS",
        "CHK-SLVERR-WINDOW-PORT-BASE",
        "CHK-DEBUG-APERTURE-DECERR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gap_decode_response_test_seq("gap_decode_response_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "GAP_DECODE_RESPONSE")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
