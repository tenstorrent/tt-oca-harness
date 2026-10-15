# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA burst-length reduction and AW decoupling observed on the SYS_OUT address channels."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_burst_shaping_test_seq import smc_dma_burst_shaping_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_burst_shaping_test(smc_base_test):
    """4 KiB copies under every CONFIG burst-shaping mode, AR and AW bursts checked."""

    required_evidence = (
        "CHK-DMA-AW-AFTER-FIRST-R",
        "CHK-DMA-AW-BEFORE-FIRST-R",
        "CHK-DMA-BURST-ALL-BITS",
        "CHK-DMA-BURST-DST-LLEN",
        "CHK-DMA-BURST-IGNORED-INDEPENDENT",
        "CHK-DMA-BURST-REDUCE-OFF",
        "CHK-DMA-BURST-SRC-LLEN",
        "CHK-NONVAC",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_burst_shaping_test_seq("smc_dma_burst_shaping_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
