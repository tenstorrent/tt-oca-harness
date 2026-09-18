# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_CG_INDEP_TEST ANCHOR: smc_zeroer_cg_indep_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_cg_indep_test_seq import smc_zeroer_cg_indep_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_cg_indep_test(smc_base_test):
    """LIVE Zeroer axi/reg CG independence."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ZINDEP-DECOUPLE",
    )
    min_evidence = 2

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
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the zeroer-DONE poll is timing-dependent.
            min_csr_accesses=10,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"ZEROER_CG_INDEP LIVE fence={seq.fence}",
        )
