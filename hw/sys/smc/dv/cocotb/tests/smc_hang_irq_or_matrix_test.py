# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang detector irq_test OR over detector pairs, drop orders and threshold zero."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_irq_or_matrix_test_seq import smc_hang_irq_or_matrix_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_irq_or_matrix_test(smc_base_test):
    """irq_test on the three detectors drives raw bit 286 as their OR; 285 and 287 stay quiet."""

    required_evidence = (
        "CHK-HANGOR-NEIGHBOURS",
        "CHK-HANGOR-ORDERS",
        "CHK-HANGOR-PAIRS",
        "CHK-HANGOR-THR0-TEST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_irq_or_matrix_test_seq("hang_irq_or_matrix_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 5, f"phases {seq.phases}, want 5"
        assert seq.accesses >= 150, f"only {seq.accesses} SEP_IN accesses issued, want >= 150"
