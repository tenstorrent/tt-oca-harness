# SPDX-License-Identifier: Apache-2.0
"""SMC OSS OCTS dual-chiplet sync test (U4-5)."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_octs_dual_sync_test_seq import smc_octs_dual_sync_test_seq


@pyuvm.test()
class smc_octs_dual_sync_test(smc_base_test):
    """U4-5: SECONDARY pad inject + PRIMARY sync/credit pad edges."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_dual_sync_test_seq("octs_dual_sync_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=0,
            proxy=False,
            details=(
                "OCTS dual-chiplet: secondary sync-then-credit COUNT + "
                "primary pad55/56 rising-edge hard-gates"
            ),
        )
