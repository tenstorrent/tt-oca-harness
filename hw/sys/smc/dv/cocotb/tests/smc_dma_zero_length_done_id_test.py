# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A zero-length DMA launch retires once per repetition.

After a launch with `LENGTH` 0, `ENABLED_ND` set and N drawn `NUM_REPETITIONS`,
`DONE_0` must read its pre-launch value plus N (`dma.adoc`, Retirement
Counting: the backend answers each zero-length row with an error response
marked as the command's last, so the command retires N times). The twelve
drawn copies and the `ENABLED_ND` clear of the `smc_dma_transfer_matrix_rand_test`
draw run first as the arm leg; each of them retires once.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_transfer_matrix_rand_test_seq import smc_dma_transfer_matrix_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_zero_length_done_id_test(smc_base_test):
    """The DMA matrix draw with DONE_0 after the zero-length launch compared to the retirement count."""

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
