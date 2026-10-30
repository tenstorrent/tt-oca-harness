# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded DMA copy geometry, burst shaping, ENABLED_ND-clear and zero-length launches."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_transfer_matrix_rand_test_seq import smc_dma_transfer_matrix_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_transfer_matrix_rand_test(smc_base_test):
    """Twelve drawn copies through the SYS_OUT responder plus two no-data launches."""

    required_evidence = (
        "CHK-DXM-BURST-BOUND",
        "CHK-DXM-BYTE-EXACT",
        "CHK-DXM-DONE-ID",
        "CHK-DXM-ND-CLEAR",
        "CHK-DXM-ZERO-LENGTH",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_transfer_matrix_rand_test_seq(
            "smc_dma_transfer_matrix_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
