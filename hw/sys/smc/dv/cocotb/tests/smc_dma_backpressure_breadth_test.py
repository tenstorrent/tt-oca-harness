# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA egress back-pressure breadth: random stalls, in-flight plateau, long hold, realignment."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_backpressure_breadth_test_seq import smc_dma_backpressure_breadth_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_backpressure_breadth_test(smc_base_test):
    """Copy through a SYS_OUT responder that stalls, delays and holds its channels."""

    required_evidence = (
        "CHK-DMA-BP-LONG-STALL",
        "CHK-DMA-BP-OUTSTANDING-CAP",
        "CHK-DMA-BP-RANDOM",
        "CHK-DMA-BP-REALIGN",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_backpressure_breadth_test_seq("smc_dma_backpressure_breadth_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
