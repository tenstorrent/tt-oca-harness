# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PLL DVFS depth bounded test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_pll_pvt_clock_config_test_seq import smc_pll_pvt_clock_config_test_seq


@pyuvm.test()
class smc_pll_dvfs_depth_test(smc_base_test):
    """Run clock-control plus bounded PLL-window reachability checker."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pll_pvt_clock_config_test_seq("pll_dvfs_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CLOCK,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=True,
            details="PLL/DVFS bounded timeout reachability checked",
        )
