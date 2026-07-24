# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM default register read test over real SYS AXI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_default_reg_rd_test_seq import smc_default_reg_rd_test_seq


@pyuvm.test()
class smc_default_reg_rd_test(smc_base_test):
    """Run a compact OSS-safe default-register read sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_default_reg_rd_test_seq("default_reg_rd_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.reads,
            proxy=False,
            details="Field-aware catalog default RO/RW-read CSR sweep checked",
        )
