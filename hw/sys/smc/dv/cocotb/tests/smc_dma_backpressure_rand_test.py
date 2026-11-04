# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Queued DMA chunks under seed-drawn SYS_OUT R and B hold windows stay byte-exact."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_backpressure_rand_test_seq import smc_dma_backpressure_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_backpressure_rand_test(smc_base_test):
    """Five to eight chunks launched under one to three drawn hold windows."""

    required_evidence = (
        "CHK-DBP-BYTES",
        "CHK-DBP-IDS",
        "CHK-DBP-QUEUE",
        "CHK-DBP-READY",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_backpressure_rand_test_seq(
            "smc_dma_backpressure_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
