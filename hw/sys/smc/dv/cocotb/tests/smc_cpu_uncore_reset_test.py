# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CPU cluster's uncore reset held on its own with every core released.

`reset_applied` has to set while the uncore reset is held and clear when it
is released.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_uncore_reset_test_seq import smc_cpu_uncore_reset_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_uncore_reset_test(smc_base_test):
    """Hold the uncore reset alone, then release it."""

    required_evidence = ("CHK-CPU-UNCORE-RESET",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_uncore_reset_test_seq("smc_cpu_uncore_reset_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.applied is not None, "the uncore reset leg did not run"
