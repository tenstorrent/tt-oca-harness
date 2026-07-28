# SPDX-License-Identifier: Apache-2.0
"""SMC OSS mailbox event IRQ source test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_mailbox_irq_test_seq import smc_mailbox_irq_test_seq
from seq_lib.smc_mailbox_vip_utils import check_mailbox_irq_source


@pyuvm.test()
class smc_mailbox_event_irq_test(smc_base_test):
    """Run mailbox IRQ-control decode plus real sync IRQ injection."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_irq_test_seq("mailbox_event_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_mailbox_irq_source(mask=0x4)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="SEP mailbox interrupt injection toggled SMC sync IRQ",
        )
