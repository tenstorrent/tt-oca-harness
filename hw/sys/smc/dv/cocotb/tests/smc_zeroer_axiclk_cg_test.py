# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_AXICLK_CG_TEST ANCHOR: smc_zeroer_axiclk_cg_test

DV-CARD: SMC_CG_P2_002 ANCHOR: smc_zeroer_axiclk_cg_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_axiclk_cg_test_seq import smc_zeroer_axiclk_cg_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_axiclk_cg_test(smc_base_test):
    """LIVE Zeroer axi_clk gating (Skill 1.5)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_zeroer_axiclk_cg_test_seq("zeroer_axiclk_cg_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-ZAXI-GATE-OFF-IDLE",
            "CHK-ZAXI-BUSY-ENABLE",
            "CHK-ZAXI-DISABLE-CG",
            "CHK-ZAXI-RESET-OVERRIDE",
            "CHK-NONVAC",
            "CHK-ZEROER-AXICLK-NOGLITCH",
            "CHK-ZEROER-AXICLK-COMPLETION",
            "CHK-NONVAC-P2",
            "CHK-TIMEOUT-PATHS",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            # Conservative stimulus floor: 45 accesses observed in the retained
            # regression run; the zeroer-DONE poll is a timing-dependent
            # remainder, so the floor is set below it. Literal here, not read
            # from `seq.accesses`.
            min_csr_accesses=35,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"ZEROER_AXICLK_CG LIVE fence={seq.fence}",
        )
