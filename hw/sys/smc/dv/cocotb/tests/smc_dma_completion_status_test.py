# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA DONE and STATUS reporting: reset values, midend bit, no-data commands, held transfer."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_completion_status_test_seq import smc_dma_completion_status_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_completion_status_test(smc_base_test):
    """DONE_0 and STATUS_0 observed at idle, during a copy, for no-data commands and a hold."""

    required_evidence = (
        "CHK-DMA-DONE-RESET",
        "CHK-DMA-STATUS-IDLE",
        "CHK-DMA-STATUS-BIT8",
        "CHK-DMA-NO-DATA-ND-CLEAR",
        "CHK-DMA-NO-DATA-REPS-ZERO",
        "CHK-DMA-POLL-IN-FLIGHT",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_completion_status_test_seq("smc_dma_completion_status_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
