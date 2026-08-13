# SPDX-License-Identifier: Apache-2.0
"""
DV-CARD: SMC_CLK_MULTI_WINDOW_TEST ANCHOR: smc_clk_multi_window_test
DV-CARD-REVISION: 1 RECORD-SHA256: b1458f8522c1c4931dd63acd0c575aef4d60110ac0aa69a77016821f04ac2a86
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_clk_multi_window_test_seq import smc_clk_multi_window_test_seq


@pyuvm.test()
class smc_clk_multi_window_test(smc_base_test):
    """LIVE hysteresis-window scaling (Skill 1.5)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_clk_multi_window_test_seq("clk_multi_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = ("CHK-HYST-WINDOW", "CHK-NONVAC", "CHK-TIMEOUT-PATHS")
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "MULTI_WINDOW LIVE: hyst min/mid/max "
                f"measured={seq.measured} cells={seq.required_cells_hit}"
            ),
        )
