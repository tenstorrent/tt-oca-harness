# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA global clock-halt request deasserts once the action drops or the halt is disabled.

Reproducer for #3390: `halt_clock_global_or_o` must be 0 once the pair that
fired the clock-halt action is quiet, its status is cleared, `EnableEap` is 0
and `DisableGlobalClockHalt` is 1.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfd_cla_clock_halt_release_test_seq import (
    smc_dfd_cla_clock_halt_release_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_cla_clock_halt_release_test(smc_base_test):
    """Fire the clock-halt action, walk the release steps, grade the request after each."""

    required_evidence = ("CHK-CLA-CLOCK-HALT-RELEASE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_clock_halt_release_test_seq("smc_dfd_cla_clock_halt_release_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
