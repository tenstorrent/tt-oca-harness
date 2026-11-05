# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The uncore reset and the warm reset return the CLINT and watchdog 0 to their reset state.

Spec: clk_rst.adoc (SMC Reset Distribution, Reset Domains).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uncore_warm_reset_clears_timers_test_seq import (
    CHK_UNCORE,
    CHK_WARM,
    smc_uncore_warm_reset_clears_timers_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uncore_warm_reset_clears_timers_test(smc_base_test):
    """Program the CLINT, PLIC and watchdog 0, then pulse the uncore reset and the warm reset."""

    required_evidence = (CHK_UNCORE, CHK_WARM)
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uncore_warm_reset_clears_timers_test_seq(
            "smc_uncore_warm_reset_clears_timers_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.passes == [CHK_UNCORE, CHK_WARM], f"legs that passed: {seq.passes}"
