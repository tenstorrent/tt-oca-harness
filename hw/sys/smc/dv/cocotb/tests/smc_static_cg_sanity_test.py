# SPDX-License-Identifier: Apache-2.0
"""
DV-CARD: SMCCGP0_002 ANCHOR: smc_static_cg_sanity_test
DV-CARD-REVISION: 1 RECORD-SHA256: 3e58481e3b0cf7321a51f26a98560768603af989a54bb69cf5e776f5b9e6d34b
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_static_cg_sanity_test_seq import smc_static_cg_sanity_test_seq


@pyuvm.test()
class smc_static_cg_sanity_test(smc_base_test):
    """P0 bring-up LIVE gate-disabled free-run (+ legacy P1 threshold)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_static_cg_sanity_test_seq("static_cg_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-DMA-GATE-DISABLED-FREE-RUN",
            "CHK-ZEROER-GATE-DISABLED-FREE-RUN",
            "CHK-NONVAC",
            # Legacy P1 tokens retained for closed P1 grade compatibility.
            "CHK-MODULE-GATING",
            "CHK-ENABLE-THRESHOLD",
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
                f"STATIC_CG P0+P1 LIVE: measured={seq.measured} "
                f"cells={seq.required_cells_hit}"
            ),
        )
