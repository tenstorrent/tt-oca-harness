# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 0 byte-enable handling of every register write over SEP_IN.

Contract SMC_POWER_TIMER_WDT_009, anchor smc_wdt_write_width_test.
Scenarios WDT-WRITE-WIDTH.S1-S9.
Sources wdt.rdl, watchdog.adoc#Register Access.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_write_width_test_seq import smc_wdt_write_width_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_write_width_test(smc_base_test):
    """Narrow and zero-strobe watchdog writes answer OKAY and act only where the strobes cover."""

    required_evidence = (
        "CHK-WDT-NARROW-KEY-FEED",
        "CHK-WDT-HALFWORD-CMP-SCALED",
        "CHK-WDT-CTRL-BYTELANES",
        "CHK-WDT-NARROW-COUNT",
        "CHK-WDT-ZERO-STROBE",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_write_width_test_seq("wdt_write_width_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.completed, "the sequence did not reach its end"
