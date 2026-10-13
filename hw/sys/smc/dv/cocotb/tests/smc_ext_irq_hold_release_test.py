# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""External inputs hold high and release at raw cpu_interrupts bits 0, 2 and 16."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_irq_hold_release_test_seq import smc_ext_irq_hold_release_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_irq_hold_release_test(smc_base_test):
    """Hold each external input for 256 rises, release it, and require no latch."""

    required_evidence = (
        "CHK-EXTHOLD-BIT0",
        "CHK-EXTHOLD-BIT2",
        "CHK-EXTHOLD-BIT16",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_irq_hold_release_test_seq("ext_irq_hold_release_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "the sequence did not finish all three hold and release steps"
        assert seq.accesses == 1, f"{seq.accesses} SEP_IN accesses issued, want 1 (scratch read)"
