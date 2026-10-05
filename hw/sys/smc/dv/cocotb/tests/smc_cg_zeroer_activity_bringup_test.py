# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_004 ANCHOR: smc_cg_zeroer_activity_bringup_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cg_zeroer_activity_bringup_test_seq import (
    smc_cg_zeroer_activity_bringup_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cg_zeroer_activity_bringup_test(smc_base_test):
    """LIVE Zeroer axi_clk + reg_clk activity-driven gate/ungate, single zero
    operation."""

    required_evidence = (
        "CHK-BUSY-UNGATES-AXI-CLK",
        "CHK-NONVAC",
        "CHK-REG-ACCESS-UNGATES-REG-CLK",
        "CHK-REG-CLK-IDLE-GATED",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_cg_zeroer_activity_bringup_test_seq("cg_zeroer_activity_bringup_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-REG-CLK-IDLE-GATED",
            "CHK-REG-ACCESS-UNGATES-REG-CLK",
            "CHK-BUSY-UNGATES-AXI-CLK",
            "CHK-NONVAC",
            "CHK-TIMEOUT-PATHS",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            # Directed stimulus floor: 15 SEP_IN AXI accesses (CG programming
            # plus the zeroer descriptor/trigger writes). Literal here, not
            # read from `seq.accesses`.
            min_csr_accesses=15,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"CG_ZEROER_ACTIVITY_BRINGUP LIVE fence={seq.fence}",
        )
