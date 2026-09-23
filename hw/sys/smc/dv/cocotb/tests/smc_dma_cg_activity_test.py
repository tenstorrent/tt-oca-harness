# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_DMA_CG_ACTIVITY_TEST ANCHOR: smc_dma_cg_activity_test

DV-CARD: SMC_CG_P2_001 ANCHOR: smc_dma_cg_activity_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dma_cg_activity_test_seq import smc_dma_cg_activity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_cg_activity_test(smc_base_test):
    """LIVE DMA activity/enable clock-gating check."""

    required_evidence = (
        "CHK-DMA-GATE-OFF",
        "CHK-DMA-GATING-DISABLED",
        "CHK-DMA-HYST-RACE",
        "CHK-DMA-HYST-SWEEP",
        "CHK-DMA-WAKEUP-BACKEND",
        "CHK-DMA-WAKEUP-FRONTEND",
        "CHK-NONVAC",
        "CHK-NONVAC-P2",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_dma_cg_activity_test_seq("dma_cg_activity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Required evidence tokens must already be in the kept log from the seq.
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
            # Stimulus floor set below the run-to-run minimum: the DMA-DONE
            # polls across the four CG evidence phases are a timing-dependent
            # remainder. Literal here, not read from `seq.accesses`.
            min_csr_accesses=70,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "DMA CG LIVE: gate-off / frontend-wakeup / "
                "backend-only-keep-enabled / gating-disabled evidence emitted "
                f"(fence={seq.fence})"
            ),
        )
