# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA commands with ENABLED_ND cleared or a zero length move no data; a valid copy does."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_invalid_descriptor_test_seq import smc_dma_invalid_descriptor_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_invalid_descriptor_test(smc_base_test):
    """No-data outcome of an ENABLED_ND-cleared and a zero-length command with a copy control."""

    required_evidence = (
        "CHK-DMA-COPY-CONTROL",
        "CHK-DMA-IRQ-PULSE-COPY",
        "CHK-DMA-ND-CLEAR-DONE-ADVANCES",
        "CHK-DMA-ND-CLEAR-MEASURED",
        "CHK-DMA-ND-CLEAR-NO-DATA",
        "CHK-DMA-SUBMIT-32BIT",
        "CHK-DMA-SUBMIT-64BIT",
        "CHK-DMA-ZEROLEN-MEASURED",
        "CHK-DMA-ZEROLEN-NO-DATA",
        "CHK-NONVAC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_invalid_descriptor_test_seq("smc_dma_invalid_descriptor_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
