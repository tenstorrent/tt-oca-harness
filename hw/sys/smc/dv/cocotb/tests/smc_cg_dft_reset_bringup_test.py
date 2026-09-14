# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_003 ANCHOR: smc_cg_dft_reset_bringup_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cg_dft_reset_bringup_test_seq import smc_cg_dft_reset_bringup_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cg_dft_reset_bringup_test(smc_base_test):
    """LIVE/CONNECTIVITY DFT test_en_i bypass + Zeroer reset-override."""

    required_evidence = (
        "CHK-DFT-BYPASS-FREE-RUN",
        "CHK-NONVAC",
        "CHK-RESET-OVERRIDE-FREE-RUN",
    )
    min_evidence = 3

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_cg_dft_reset_bringup_test_seq("cg_dft_reset_bringup_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = ("CHK-DFT-BYPASS-FREE-RUN", "CHK-RESET-OVERRIDE-FREE-RUN", "CHK-NONVAC")
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
            details=f"CG_DFT_RESET_BRINGUP LIVE fence={seq.fence}",
        )
