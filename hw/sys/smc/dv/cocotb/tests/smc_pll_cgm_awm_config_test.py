# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap: PLL CGM 0/1 + AWM 0/1 CSR sweep."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_pll_cgm_awm_config_test_seq import smc_pll_cgm_awm_config_test_seq


@pyuvm.test()
class smc_pll_cgm_awm_config_test(smc_base_test):
    """P1 coverage-gap depth: PLL CGM 0/1 + AWM 0/1 CSR sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pll_cgm_awm_config_test_seq("smc_pll_cgm_awm_config_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CLOCK,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=True,
            details="P1 coverage-gap: PLL CGM 0/1 + AWM 0/1 CSR sweep",
        )
