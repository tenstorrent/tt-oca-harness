# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA descriptors queued behind a stalled destination, and a read error mid-burst."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_backpressure_test_seq import smc_dma_backpressure_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_backpressure_test(smc_base_test):
    """Queue DMA descriptors behind a destination whose responses are held."""

    required_evidence = (
        "CHK-DMA-BACKPRESSURE",
        "CHK-DMA-READ-ERROR-BEAT",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_backpressure_test_seq("smc_dma_backpressure_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
