# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS JTAG-adjacent reset pin-level test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_jtag_reset_proxy_test_seq import smc_jtag_reset_proxy_test_seq
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_reset_proxy_test(smc_base_test):
    """Run JTAG-adjacent CSR health checks plus CPU JTAG pin checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_reset_proxy_test_seq("jtag_reset_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=getattr(seq, "accesses", 0),
            proxy=True,
            details="CPU JTAG TCK/TMS/TDI/reset driven and TDO checked",
        )
