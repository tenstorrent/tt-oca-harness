# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded cool-pin, FLR, cold and watchdog resets mid-operation; register retention by domain."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_reset_mid_transaction_rand_test_seq import (
    PASSES,
    SPM_EXTRA_MAX,
    smc_reset_mid_transaction_rand_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_mid_transaction_rand_test(smc_base_test):
    """Each drawn reset resets exactly its domain's registers and keeps every other value."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-RMT-ALLZERO-X-FREE",
        "CHK-RMT-COLD-ONLY-RETAIN",
        "CHK-RMT-PRIMARY-RESET-VALUES",
        "CHK-RMT-RECOVERY",
        "CHK-RMT-SCRATCH-LOGGED",
        "CHK-RMT-WARM-EQUATION",
        "CHK-RMT-WARM-RETAIN",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_mid_transaction_rand_test_seq(
            "smc_reset_mid_transaction_rand_test_seq", seed=self.random_seed()
        )

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done and PASSES <= len(seq.passes) <= PASSES + SPM_EXTRA_MAX, (
            "reset mid-transaction passes incomplete"
        )
