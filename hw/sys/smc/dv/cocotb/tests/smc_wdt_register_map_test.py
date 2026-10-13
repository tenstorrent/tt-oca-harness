# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Contract SMC_POWER_TIMER_WDT_007, anchor smc_wdt_register_map_test.

Allocated scenarios: WDT-APERTURE.S2-S5, WDT-CTRL-FIELDS.S1-S4, WDT-CMP.S2.
Spec sources: hw/sys/smc/doc/watchdog.adoc (Operation, Register Access),
hw/sys/smc/regs/blocks/wdt/wdt.rdl.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_register_map_test_seq import smc_wdt_register_map_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_register_map_test(smc_base_test):
    """Four-core watchdog aperture isolation, offset decode, CTRL fields and CMP width."""

    required_evidence = (
        "CHK-WDT-CTRL-RESET",
        "CHK-WDT-OFFSET-DECODE",
        "CHK-WDT-APERTURE-ISOLATION",
        "CHK-WDT-APERTURE-INTERLEAVE",
        "CHK-WDT-CTRL-FIELD-READBACK",
        "CHK-WDT-CTRL-RESERVED",
        "CHK-WDT-CTRL-LOCKED-WRITE",
        "CHK-WDT-CMP-WIDE-WRITE",
        "CHK-NONVAC",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_register_map_test_seq("wdt_register_map_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
