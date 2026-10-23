# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs at the corners of SIZE and DEST_ADDR.

The zero-byte job has to leave its destination poisoned and book no write
transaction; the page-crossing job has to zero exactly its sixteen bytes in at
least two write transactions. DEST_ADDR is then walked as storage and as a
start address: one job per single-bit address over the 56-bit data address,
unaligned starts, a start with SIZE 0 and a start above the data address range.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_zeroer_size_corners_test_seq import smc_zeroer_size_corners_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_size_corners_test(smc_base_test):
    """Zero-byte, page-crossing, single-bit, unaligned and above-range zeroer starts."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-ZEROER-ABOVE-RANGE",
        "CHK-ZEROER-ADDR-WALK",
        "CHK-ZEROER-BUSY",
        "CHK-ZEROER-DEST-PATTERN",
        "CHK-ZEROER-EMPTY-JOB",
        "CHK-ZEROER-PAGE-CROSS",
        "CHK-ZEROER-SIZE0",
        "CHK-ZEROER-UNALIGNED",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_size_corners_test_seq("smc_zeroer_size_corners_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
