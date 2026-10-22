# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_005 ANCHOR: smc_ext_irq_hold_release_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 06aaaeaac8e1c77902b9ddfdb6242e46b21d4aeec99507ee10f39385e797136a
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 6 ENV: cocotb
"""External inputs 0 and 2..16 hold high and release at the raw cpu_interrupts bits."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_irq_hold_release_test_seq import smc_ext_irq_hold_release_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_irq_hold_release_test(smc_base_test):
    """Hold each drivable external input for 256 rises, release it, and require no latch."""

    required_evidence = (
        "CHK-EXTHOLD-BIT0",
        "CHK-EXTHOLD-BIT16",
        "CHK-EXTHOLD-BIT2",
        "CHK-EXTIRQ-ASSERT",
        "CHK-EXTIRQ-ISOLATION",
        "CHK-EXTIRQ-RELEASE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_irq_hold_release_test_seq("ext_irq_hold_release_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "the sequence did not finish the walk over inputs 0 and 2..16"
        assert seq.accesses == 1, f"{seq.accesses} SEP_IN accesses issued, want 1 (scratch read)"
