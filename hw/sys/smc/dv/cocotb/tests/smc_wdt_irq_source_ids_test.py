# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC raw interrupt vector width, SEP watchdog indication on bit 282, core-2 WDT PLIC pending."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_irq_source_ids_test_seq import smc_wdt_irq_source_ids_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_irq_source_ids_test(smc_base_test):
    """The raw vector is 328 bits; SEP WDT reset bit 282 and core-2 WDT pending are independent."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SEP-WDT-IRQ-DISTINCT",
        "CHK-SEP-WDT-IRQ-LEVEL",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_irq_source_ids_test_seq("wdt_irq_source_ids_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fence_done, "ordered fence did not complete"
