# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_001 ANCHOR: smc_clk_running_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_clk_running_test_seq import smc_clk_running_test_seq


@pyuvm.test()
class smc_clk_running_test(smc_base_test):
    """P0 bring-up LIVE CG enable / idle gate / DMA ungate (Skill 1.5)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_clk_running_test_seq("clk_running_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-CG-ENABLE-READBACK",
            "CHK-IDLE-GATED-BASELINE",
            "CHK-DMA-ACTIVITY-UNGATE",
            "CHK-TIMEOUT-PATHS",
            "CHK-NONVAC",
            # Legacy P1 token retained for closed P1 grade compatibility.
            "CHK-ACTIVE-RUNNING",
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
                "CLK_RUNNING P0 LIVE: CG-enable / idle-gated / DMA-ungate "
                f"evidence emitted (fence={seq.fence})"
            ),
        )
