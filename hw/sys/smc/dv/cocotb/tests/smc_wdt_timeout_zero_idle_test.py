# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""WDT_TIMEOUT written to 0 with no first-stage timeout leaves the second stage idle.

Reproducer for #3386: with no core's first-stage timeout raised, a write of 0
to `CPU_CTRL.WDT_TIMEOUT` must leave `smc_wdt_second_timeout_o` low and the
warm reset released.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_timeout_zero_idle_test_seq import smc_wdt_timeout_zero_idle_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_timeout_zero_idle_test(smc_base_test):
    """Write WDT_TIMEOUT=0 with the watchdog idle, sample, restore, then grade."""

    required_evidence = ("CHK-WDT-TIMEOUT-ZERO-IDLE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_timeout_zero_idle_test_seq("smc_wdt_timeout_zero_idle_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
