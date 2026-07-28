# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM iJTAG-adjacent pin-level smoke (Batch C)."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_ijtag_basic_test_seq import smc_ijtag_basic_test_seq
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip


@pyuvm.test()
class smc_ijtag_basic_test(smc_base_test):
    """Run the SMC OSS iJTAG-adjacent CSR and CPU JTAG pin scenario."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ijtag_basic_test_seq("ijtag_basic_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=getattr(seq, "accesses", 0),
            proxy=False,
            details="CPU JTAG TCK/TMS/TDI/reset driven and TDO checked",
        )
