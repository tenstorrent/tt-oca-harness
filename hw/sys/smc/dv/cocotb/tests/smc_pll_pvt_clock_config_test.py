# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PLL/PVT clock CSR precheck."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_pll_pvt_clock_config_test_seq import (
    smc_pll_pvt_clock_config_test_seq,
)


@pyuvm.test()
class smc_pll_pvt_clock_config_test(smc_base_test):
    """Run the PLL/PVT/clock-control representative CSR precheck."""

    async def run_scenario(self) -> None:
        seq = smc_pll_pvt_clock_config_test_seq("pll_pvt_clock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
