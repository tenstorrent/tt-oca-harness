# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS zeroer payload sanity test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_dma_timeout_test_seq import smc_zeroer_dma_timeout_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_sanity_test(smc_base_test):
    """Run zeroer over output-fabric payload bytes and check the model."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_dma_timeout_test_seq("zeroer_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "Zeroer cleared output-fabric payload via JTAG AXI readback "
                f"(checked_bytes={seq.checked_bytes}; neighbour poison unchanged)"
            ),
        )
