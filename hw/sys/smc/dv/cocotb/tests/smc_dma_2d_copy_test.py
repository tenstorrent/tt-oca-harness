# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA two-dimensional copy breadth: strides, row counts, unaligned rows, single ID, edges."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_2d_copy_test_seq import smc_dma_2d_copy_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_2d_copy_test(smc_base_test):
    """2D copies through the SYS_OUT responder checked row by row."""

    required_evidence = (
        "CHK-DMA-2D-INDEP-STRIDES",
        "CHK-DMA-2D-ROW-COUNTS",
        "CHK-DMA-2D-UNALIGNED-ROWS",
        "CHK-DMA-2D-SINGLE-ID",
        "CHK-DMA-2D-STRIDE-EDGES",
        "CHK-DMA-2D-WRAP-2POW56",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_2d_copy_test_seq("smc_dma_2d_copy_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
