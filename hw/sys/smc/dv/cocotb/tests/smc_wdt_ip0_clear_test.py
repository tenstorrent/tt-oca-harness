# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 0 CTRL.wdogip0 set, hold and clear sequence.

Sources wdt.rdl, watchdog.adoc#Operation, smc-programming.adoc#watchdog.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_ip0_clear_test_seq import smc_wdt_ip0_clear_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_ip0_clear_test(smc_base_test):
    """wdogip0 sets at the compare, holds above it and clears only through KEY and a CTRL write."""

    required_evidence = (
        "CHK-WDT-IP0-SET",
        "CHK-WDT-IP0-CLEAR-SEQUENCE",
        "CHK-WDT-IP0-UNLOCK-CONSUMED",
        "CHK-WDT-IP0-NO-CLEAR-ABOVE",
        "CHK-WDT-IP0-RESET-AFTER-CLEAR",
        "CHK-WDT-IP0-WRITE-ONE",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_ip0_clear_test_seq("wdt_ip0_clear_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.completed, "the sequence did not reach its end"
