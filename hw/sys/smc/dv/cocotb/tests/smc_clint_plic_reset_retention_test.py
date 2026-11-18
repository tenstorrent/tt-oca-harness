# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLINT tick rate and reset, and PLIC and MTIMECMP retention across a cool reset."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_clint_plic_reset_retention_test_seq import (
    smc_clint_plic_reset_retention_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_clint_plic_reset_retention_test(smc_base_test):
    """MTIME ticks once per 1000 rises and resets; MTIMECMP and the PLIC words survive a cool reset."""

    required_evidence = (
        "CHK-CLINT-MTIME-RESET-ZERO",
        "CHK-CLINT-MTIME-TICK-1000",
        "CHK-CLINT-MTIMECMP-RETAIN",
        "CHK-NONVAC",
        "CHK-PLIC-REGS-RETAIN-WARM",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clint_plic_reset_retention_test_seq("clint_plic_reset_retention_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
