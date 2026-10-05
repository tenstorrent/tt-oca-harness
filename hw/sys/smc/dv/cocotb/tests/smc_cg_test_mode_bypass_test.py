# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_CG_TEST_MODE_BYPASS_TEST ANCHOR: smc_cg_test_mode_bypass_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cg_test_mode_bypass_test_seq import smc_cg_test_mode_bypass_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cg_test_mode_bypass_test(smc_base_test):
    """LIVE test_en_i DFT bypass."""

    required_evidence = (
        "CHK-DFT-BYPASS-DMA",
        "CHK-DFT-BYPASS-ZEROER",
        "CHK-NONVAC",
    )
    min_evidence = 3

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_cg_test_mode_bypass_test_seq("cg_test_mode_bypass_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = ("CHK-DFT-BYPASS-DMA", "CHK-DFT-BYPASS-ZEROER", "CHK-NONVAC")
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            # Directed stimulus floor: 2 SEP_IN AXI CLOCK_GATE_CONTROL
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=2,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"CG_TEST_MODE_BYPASS LIVE fence={seq.fence}",
        )
