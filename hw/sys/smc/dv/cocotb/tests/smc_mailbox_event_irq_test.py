# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS mailbox event IRQ source test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_mailbox_irq_test_seq import smc_mailbox_irq_test_seq
from seq_lib.smc_mailbox_vip_utils import check_mailbox_irq_source
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_event_irq_test(smc_base_test):
    """Run mailbox IRQ-control decode plus real sync IRQ injection."""

    required_evidence = (
        "CHK-MAILBOX-IRQ-ASSERT",
        "CHK-MAILBOX-IRQ-CLEAR",
        "CHK-MAILBOX-IRQ-IDLE",
        "CHK-MAILBOX-IRQ-SOURCE",
        "CHK-MAILBOX-IRQT-CLAMP",
        "CHK-MAILBOX-IRQT-IN-RANGE",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_irq_test_seq("mailbox_event_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_mailbox_irq_source(mask=0x4)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            # Directed stimulus floor: 19 SEP_IN AXI mailbox event/IRQ-control
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=19,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`, which the
            # sequence increments on dispatch regardless of what came back.
            # The floor then compares a DUT-completed count against a literal.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            # Names the observable actually checked: check_mailbox_irq_source
            # reads tb_mailbox_irq_any (tb_top.sv,
            # |u_dut.u_smc.peripheral_interrupts[7:0]). tb_sync_irq is a
            # different net in tb_top.sv and is not sampled here.
            details=(
                "SEP mailbox interrupt injection raised tb_mailbox_irq_any "
                "(peripheral_interrupts[7:0]); tb_sync_irq not sampled here"
            ),
        )
