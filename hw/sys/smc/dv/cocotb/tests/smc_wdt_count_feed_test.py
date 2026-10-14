# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog COUNT enable conditions, COUNT write semantics, COUNT_HI read and FEED write.

Sources wdt.rdl, smc-programming.adoc#watchdog, watchdog.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_count_feed_test_seq import smc_wdt_count_feed_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_count_feed_test(smc_base_test):
    """COUNT counts under wdogenalways or wdogcoreawake, accepts keyed writes and clears on FEED."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-WDT-COREAWAKE",
        "CHK-WDT-COUNT-ENABLE-MATRIX",
        "CHK-WDT-COUNT-ROLLOVER",
        "CHK-WDT-COUNT-WRITE",
        "CHK-WDT-COUNTHI-ZERO",
        "CHK-WDT-FEED-NONMAGIC",
        "CHK-WDT-FEED-RESET",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_count_feed_test_seq("wdt_count_feed_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.completed, "the sequence did not reach its end"
