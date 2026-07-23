# SPDX-License-Identifier: Apache-2.0
"""GitHub Project P0 alias for AVSBus sideband precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_sideband_vip_utils import check_sideband_observability
from seq_lib.smc_sideband_protocol_smoke_test_seq import (
    smc_sideband_protocol_smoke_test_seq,
)


@pyuvm.test()
class smc_avsbus_sanity_test(smc_base_test):
    """Run the AVSBus proxy scenario tracked by the P0 project issue."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sideband_protocol_smoke_test_seq("avsbus_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_sideband_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=True,
            details="AVSBus CSR decode plus bounded IRQ/state observability",
        )
