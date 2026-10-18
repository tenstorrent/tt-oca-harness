# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA reference-mode copies: 2D rows, linear, four queued requests, page-aligned start."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dma_traffic_shape_test_seq import (
    MIN_SEP_IN_ACCESSES,
    smc_dma_traffic_shape_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_traffic_shape_test(smc_base_test):
    """Copies with DECOUPLE_RW and DECOUPLE_AW clear land byte for byte in the responder."""

    required_evidence = (
        "CHK-DTS-COUPLED-COPY",
        "CHK-DTS-LINEAR",
        "CHK-DTS-PAGE-ALIGNED",
        "CHK-DTS-QUEUE-FOUR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_traffic_shape_test_seq("dma_traffic_shape_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.finished, "the sequence did not reach its teardown step"
        assert seq.accesses >= MIN_SEP_IN_ACCESSES, (
            f"only {seq.accesses} SEP_IN accesses issued, want >= {MIN_SEP_IN_ACCESSES}"
        )
