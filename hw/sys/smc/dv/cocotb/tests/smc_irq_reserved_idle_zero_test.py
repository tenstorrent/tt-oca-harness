# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reserved, internal and peripheral-owned raw tb_cpu_interrupts positions at idle."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_reserved_idle_zero_test_seq import smc_irq_reserved_idle_zero_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_reserved_idle_zero_test(smc_base_test):
    """Tied raw bits 287 and 327:324 read 0 over a 256-rise idle window; the rest are logged."""

    required_evidence = (
        "CHK-RSVDIDLE-287",
        "CHK-RSVDIDLE-TAIL",
        "CHK-RSVDIDLE-INTERNAL-LOG",
        "CHK-RSVDIDLE-PERIPH-LOG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_irq_reserved_idle_zero_test_seq("irq_reserved_idle_zero_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 5, f"phases {seq.phases}, want 5"
        assert seq.accesses >= 1, f"only {seq.accesses} SEP_IN accesses issued, want >= 1"
