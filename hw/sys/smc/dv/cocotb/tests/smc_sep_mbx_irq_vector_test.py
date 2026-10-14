# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP mailbox interrupt inputs against raw tb_cpu_interrupts bits 263:256."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sep_mbx_irq_vector_test_seq import smc_sep_mbx_irq_vector_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sep_mbx_irq_vector_test(smc_base_test):
    """Walk, hold, subsets and latency log on tb_sep_mailbox_interrupts[7:0]."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SEPMBX-HOLD",
        "CHK-SEPMBX-LATENCY-LOG",
        "CHK-SEPMBX-SUBSETS",
        "CHK-SEPMBX-WALK",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sep_mbx_irq_vector_test_seq("sep_mbx_irq_vector_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 51, f"phases {seq.phases}, want 51"
        assert seq.accesses >= 1, f"only {seq.accesses} SEP_IN accesses issued, want >= 1"
