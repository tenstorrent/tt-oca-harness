# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Core 0 watchdog KEY protocol corners and relock on every register.

Spec sources: hw/sys/smc/doc/watchdog.adoc (Register Access), hw/sys/smc/regs/blocks/wdt/wdt.rdl.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_key_relock_test_seq import smc_wdt_key_relock_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_key_relock_test(smc_base_test):
    """Core 0 watchdog KEY corners and relock after a write to each register."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-WDT-KEY-NONMAGIC",
        "CHK-WDT-KEY-READ-UNLOCKED",
        "CHK-WDT-KEY-REPEATED-MAGIC",
        "CHK-WDT-LOCKED-WRITE-DROP",
        "CHK-WDT-RELOCK-CMP",
        "CHK-WDT-RELOCK-REGISTERS",
        "CHK-WDT-WIDE-WRITE-LOCK",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_key_relock_test_seq("wdt_key_relock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
