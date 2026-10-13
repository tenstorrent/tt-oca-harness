# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 0 SCALED_COUNT shift relation and the wdogzerocmp count clear.

Contract SMC_POWER_TIMER_WDT_011, anchor smc_wdt_scale_zerocmp_test.
Scenarios WDT-SCALE.S1-S4 and WDT-ZEROCMP.S1-S5.
Sources wdt.rdl, smc-programming.adoc#watchdog.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_scale_zerocmp_test_seq import smc_wdt_scale_zerocmp_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_scale_zerocmp_test(smc_base_test):
    """SCALED_COUNT equals COUNT >> wdogscale and wdogzerocmp clears COUNT at the compare."""

    required_evidence = (
        "CHK-WDT-SCALED-COUNT-WIDE",
        "CHK-WDT-SCALED-COUNT-SHIFT",
        "CHK-WDT-ZEROCMP-OFF",
        "CHK-WDT-ZEROCMP-CMP0",
        "CHK-WDT-ZEROCMP-CLEAR",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_scale_zerocmp_test_seq("wdt_scale_zerocmp_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.completed, "the sequence did not reach its end"
