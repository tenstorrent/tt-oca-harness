# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap Round 5: PVT droop-monitor sweep."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_pvt_droop_test_seq import smc_pvt_droop_test_seq


@pyuvm.test()
class smc_pvt_droop_test(smc_base_test):
    """P1 coverage-gap depth: PVT droop-monitor sub-block (0xC000_7400)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pvt_droop_test_seq("smc_pvt_droop_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CLOCK,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=True,
            details=(
                "CSR/DECERR window sweep: PVT_WRAP_DROOP (no sensor model; U5 policy)"
            ),
        )
