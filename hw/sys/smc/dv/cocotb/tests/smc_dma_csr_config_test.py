# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA shared configuration registers: storage, fields, retention after copies, aliases."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_csr_config_test_seq import smc_dma_csr_config_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_csr_config_test(smc_base_test):
    """Read back the twelve descriptor registers and CONFIG through every access shape."""

    required_evidence = (
        "CHK-DMA-CSR-OWN-VALUE",
        "CHK-DMA-CSR-HI-FULL32",
        "CHK-DMA-CSR-CONFIG-FIELDS",
        "CHK-DMA-CSR-RETAIN-AFTER-COPY",
        "CHK-DMA-CSR-GLOBAL-ALIAS",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_csr_config_test_seq("smc_dma_csr_config_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
