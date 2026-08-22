# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_CG_INDEP_TEST ANCHOR: smc_zeroer_cg_indep_test
DV-CARD-REVISION: 1 RECORD-SHA256: 46ad998bc85c45be9ff0180d25267976c65047f0d983dec945caf0e9eebee833
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md @ artifact_revision 3 ENV: cocotb
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_zeroer_cg_indep_test_seq import smc_zeroer_cg_indep_test_seq


@pyuvm.test()
class smc_zeroer_cg_indep_test(smc_base_test):
    """LIVE Zeroer axi/reg CG independence (Skill 1.5)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_zeroer_cg_indep_test_seq("zeroer_cg_indep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-ZINDEP-DECOUPLE",
            "CHK-NONVAC",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"ZEROER_CG_INDEP LIVE fence={seq.fence}",
        )
