# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded watchdog second-timeout warm reset and the watchdog state after it."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_warm_reset_rand_test_seq import smc_wdt_warm_reset_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_warm_reset_rand_test(smc_base_test):
    """Drawn core and timeouts: the first timeout holds, the second asserts the warm reset."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-WWR-FIRST-NO-RESET",
        "CHK-WWR-SECOND-WARM",
        "CHK-WWR-STATE-XFREE",
        "CHK-WWR-STICKY",
        "CHK-WWR-WARM-TERMS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_warm_reset_rand_test_seq(
            "smc_wdt_warm_reset_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "watchdog warm reset sequence did not complete"
