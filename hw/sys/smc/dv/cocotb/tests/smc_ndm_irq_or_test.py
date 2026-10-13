# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDM reset request bits ORed into raw tb_cpu_interrupts bit 267."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ndm_irq_or_test_seq import smc_ndm_irq_or_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ndm_irq_or_test(smc_base_test):
    """Each request bit alone, OR drop orders and a 256-rise hold against the baseline."""

    required_evidence = (
        "CHK-NDM-EACH-ALONE",
        "CHK-NDM-OR-DROP",
        "CHK-NDM-HOLD",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ndm_irq_or_test_seq("ndm_irq_or_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 18, f"phases {seq.phases}, want 18"
        assert seq.accesses >= 1, f"only {seq.accesses} SEP_IN accesses issued, want >= 1"
