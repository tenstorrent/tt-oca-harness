# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P0 alias for the mailbox CSR precheck."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_irq_test_seq import smc_mailbox_irq_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_idle_test(smc_base_test):
    """Run the mailbox status and IRQ-control CSR precheck."""

    required_evidence = (
        "CHK-MAILBOX-IRQT-CLAMP",
        "CHK-MAILBOX-IRQT-IN-RANGE",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_mailbox_irq_test_seq("mailbox_idle_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
