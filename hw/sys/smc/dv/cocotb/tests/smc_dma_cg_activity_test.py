# SPDX-License-Identifier: Apache-2.0
"""
DV-CARD: SMC_DMA_CG_ACTIVITY_TEST ANCHOR: smc_dma_cg_activity_test
DV-CARD-REVISION: 2 RECORD-SHA256: b1f928140c5123ae1298877e726f91b309ba15c3b287fb236f723b3582d51653
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb

DV-CARD: SMC_CG_P2_001 ANCHOR: smc_dma_cg_activity_test
DV-CARD-REVISION: 1 RECORD-SHA256: f30a819ece07cac193724665274c74e6512a18c0771b7fde11375464acf5489a
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_dma_cg_activity_test_seq import smc_dma_cg_activity_test_seq


@pyuvm.test()
class smc_dma_cg_activity_test(smc_base_test):
    """LIVE DMA activity/enable clock-gating check (Skill 1.5)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_dma_cg_activity_test_seq("dma_cg_activity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Required evidence tokens must already be in the kept log from the seq.
        # P1 tokens are unchanged (additive extension keeps the closed P1 grade
        # valid); the P2 (SMC_CG_P2_001) tokens are appended.
        required = (
            "CHK-DMA-GATE-OFF",
            "CHK-DMA-WAKEUP-FRONTEND",
            "CHK-DMA-WAKEUP-BACKEND",
            "CHK-DMA-GATING-DISABLED",
            "CHK-NONVAC",
            "CHK-DMA-HYST-SWEEP",
            "CHK-DMA-HYST-RACE",
            "CHK-NONVAC-P2",
            "CHK-TIMEOUT-PATHS",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "DMA CG LIVE: gate-off / frontend-wakeup / "
                "backend-only-keep-enabled / gating-disabled evidence emitted "
                f"(fence={seq.fence})"
            ),
        )
