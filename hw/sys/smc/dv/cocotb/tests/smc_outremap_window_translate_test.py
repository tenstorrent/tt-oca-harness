# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG writes through the M-mode and Xvisor remap windows land at the region targets."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outremap_window_translate_test_seq import (
    ACCESS_FLOOR,
    smc_outremap_window_translate_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-MMODE-EDGES",
    "CHK-MMODE-REGIONS",
    "CHK-NONVAC",
    "CHK-OUTREMAP-IDENTITY-RESET",
    "CHK-OUTREMAP-VALID-TOGGLE",
    "CHK-OUTROUTE-DIRECT-ADDRS",
    "CHK-TIMEOUT-PATHS",
    "CHK-XVISOR-EDGES",
    "CHK-XVISOR-INDEPENDENT",
    "CHK-XVISOR-REGIONS",
)


@pyuvm.test()
class smc_outremap_window_translate_test(smc_base_test):
    """Regions 0, 3, 7, window edges, region independence and valid toggled under load."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outremap_window_translate_test_seq("outremap_window_translate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        total = seq.accesses + seq.jtag_accesses
        assert total >= ACCESS_FLOOR, f"{total} accesses issued, floor {ACCESS_FLOOR}"
