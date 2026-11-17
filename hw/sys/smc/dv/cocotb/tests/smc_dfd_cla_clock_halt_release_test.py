# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA global clock-halt request is held until primary reset; the mask gates it.

`halt_clock_global_or_o` stays 1 once the pair that fired the clock-halt
action is quiet, its status is cleared, `EnableEap` is 0 and
`DisableGlobalClockHalt` is 1; it reads 0 with `xtrig_clk_halt_mask` bit 0
cleared and 1 again once the bit is set back.
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

    required_evidence = ("CHK-CLA-CLOCK-HALT-HELD",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_clock_halt_release_test_seq("smc_dfd_cla_clock_halt_release_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
