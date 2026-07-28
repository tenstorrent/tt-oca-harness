# SPDX-License-Identifier: Apache-2.0
"""SMC OSS chiplet register JTAG pin-level test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_jtag_dft_timeout_proxy_test_seq import (
    smc_jtag_dft_timeout_proxy_test_seq,
)
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip


@pyuvm.test()
class smc_chiplet_reg_jtag_test(smc_base_test):
    """Run public DFT blocked-window timeout coverage plus CPU JTAG pin checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dft_timeout_proxy_test_seq("chiplet_reg_jtag_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=getattr(seq, "accesses", 0),
            proxy=False,
            details="CPU JTAG TCK/TMS/TDI/reset driven and TDO checked",
        )
