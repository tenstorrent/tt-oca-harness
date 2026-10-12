# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA linear copy breadth: offsets, 2 KiB bursts, large sizes, 56-bit addresses, overlap, random."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_linear_copy_test_seq import smc_dma_linear_copy_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_linear_copy_test(smc_base_test):
    """Linear copies through the SYS_OUT responder checked byte for byte."""

    required_evidence = (
        "CHK-DMA-LIN-UNALIGNED",
        "CHK-DMA-LIN-2KIB-BOUNDARY",
        "CHK-DMA-LIN-LARGE",
        "CHK-DMA-LIN-HI-ADDR",
        "CHK-DMA-LIN-OVERLAP",
        "CHK-DMA-LIN-RANDOM",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_linear_copy_test_seq("smc_dma_linear_copy_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
