# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A zeroer job of zero bytes, and one crossing a page boundary from an unaligned start.

The zero-byte job has to leave its destination poisoned and book no write
transaction; the page-crossing job has to zero exactly its sixteen bytes in at
least two write transactions.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_zeroer_size_corners_test_seq import smc_zeroer_size_corners_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_size_corners_test(smc_base_test):
    """A zero-byte job and a job crossing a page boundary from an unaligned start."""

    required_evidence = (
        "CHK-ZEROER-EMPTY-JOB",
        "CHK-ZEROER-PAGE-CROSS",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_size_corners_test_seq("smc_zeroer_size_corners_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
