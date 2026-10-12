# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA effective field widths: upper register bits discarded, 56-bit addresses preserved."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_field_widths_test_seq import smc_dma_field_widths_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_field_widths_test(smc_base_test):
    """Copy with HI words carrying bits above the effective widths and bits 55:32."""

    required_evidence = (
        "CHK-DMA-FW-ADDR-TOP-BYTE",
        "CHK-DMA-FW-LENGTH-TOP-BYTE",
        "CHK-DMA-FW-STRIDE-TOP-BYTE",
        "CHK-DMA-FW-REPS-HI",
        "CHK-DMA-FW-ADDR-55-32",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_field_widths_test_seq("smc_dma_field_widths_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
