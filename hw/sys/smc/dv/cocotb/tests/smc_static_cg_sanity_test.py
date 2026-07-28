# SPDX-License-Identifier: Apache-2.0
"""SMC OSS static clock-gate sanity bounded test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_pll_pvt_clock_config_test_seq import smc_pll_pvt_clock_config_test_seq


@pyuvm.test()
class smc_static_cg_sanity_test(smc_base_test):
    """Run clock-gate CSR reachability as the static CG checker."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pll_pvt_clock_config_test_seq("static_cg_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CLOCK,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="Clock-gate CSR and bounded PLL/PVT timeout reachability checked",
        )
