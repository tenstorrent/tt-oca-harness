# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL MUTEX[0..3] hold, release values, independence and liveness.

Contract SMC_CPU_CTRL_013, anchor smc_cpu_ctrl_mutex_all_test.
Scenarios: CPUCTRL-MUTEX.S2, CPUCTRL-MUTEX.S3, CPUCTRL-MUTEX.S4, CPUCTRL-MUTEX.S5, CPUCTRL-MUTEX.S6.
Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (MUTEX, MUTEX[4]), generated cpu_ctrl.h.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_mutex_all_test_seq import smc_cpu_ctrl_mutex_all_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_mutex_all_test(smc_base_test):
    """MUTEX[0..3] held reads, release values, independence, b2b and stalled response."""

    required_evidence = (
        "CHK-MUTEX-HELD-READS",
        "CHK-MUTEX-RELEASE-VALUES",
        "CHK-MUTEX-INDEP",
        "CHK-MUTEX-BACK2BACK",
        "CHK-MUTEX-RSTALL",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_mutex_all_test_seq("cpu_ctrl_mutex_all_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
