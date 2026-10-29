# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A zero-length DMA launch retires the one transfer ID its launch read returned.

Reproducer for #3509: after a launch with `LENGTH` 0 and `ENABLED_ND` set,
`DONE_0` must equal the ID the `NEXT_ID_0` read returned (`dma.adoc`: a
command with a length of 0 still retires a transfer ID), not that ID plus the
drawn `NUM_REPETITIONS` less one. The twelve drawn copies and the `ENABLED_ND`
clear of the `smc_dma_transfer_matrix_rand_test` draw run first as the arm leg.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_transfer_matrix_rand_test_seq import smc_dma_transfer_matrix_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_zero_length_done_id_test(smc_base_test):
    """The DMA matrix draw with DONE_0 after the zero-length launch graded."""

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
            "smc_dma_transfer_matrix_rand_test_seq",
            seed=self.random_seed(),
            grade_zero_length_done=True,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
