# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 1's COUNT and CTRL across a core reset held through RESET_CTRL.

Spec: clk_rst.adoc (SMC Reset Distribution, NOTE on the watchdog core-reset input).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_count_across_core_reset_test_seq import (
    CHK_FROZEN,
    CHK_SURVIVES,
    smc_wdt_count_across_core_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_count_across_core_reset_test(smc_base_test):
    """COUNT freezes inside a core reset hold, survives it, and clears on the uncore reset."""

    required_evidence = (CHK_FROZEN, CHK_SURVIVES)
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_count_across_core_reset_test_seq("smc_wdt_count_across_core_reset_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.passes == [CHK_FROZEN, CHK_SURVIVES], f"legs that passed: {seq.passes}"
