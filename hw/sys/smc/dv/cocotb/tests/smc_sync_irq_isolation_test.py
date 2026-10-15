# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""sync_irq_o follows SYNC_REG.sync only and leaves the raw interrupt vector unchanged."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sync_irq_isolation_test_seq import smc_sync_irq_isolation_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sync_irq_isolation_test(smc_base_test):
    """SYNC_REG set and clear leave the vector at baseline; asserted sources do not raise sync."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SYNCIRQ-POSCTRL",
        "CHK-SYNCIRQ-SET-CLR",
        "CHK-SYNCIRQ-SOURCES-ZERO",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sync_irq_isolation_test_seq("sync_irq_isolation_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 5, f"phases {seq.phases}, want 5"
        assert seq.accesses >= 9, f"only {seq.accesses} SEP_IN accesses issued, want >= 9"
