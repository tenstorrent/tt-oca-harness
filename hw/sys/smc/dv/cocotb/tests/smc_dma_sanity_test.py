# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS DMA source-to-destination payload test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_dma_sanity_test_seq import smc_dma_sanity_test_seq


@pyuvm.test()
class smc_dma_sanity_test(smc_base_test):
    """Run DMA copy over output-fabric payload bytes and check the model."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_sanity_test_seq("dma_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "DMA copied real output-fabric source bytes to destination and matched "
                f"memory model (checked_bytes={seq.checked_bytes}, "
                f"start_id={seq.start_id}, done_id={seq.done_id})"
            ),
        )
