# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYNC_REG.sync drives sync_irq_o and only bit 0 is implemented."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sync_reg_irq_test_seq import smc_sync_reg_irq_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sync_reg_irq_test(smc_base_test):
    """Write SYNC_REG and follow sync_irq_o; upper bits do not reach the pin."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SYNC-DRIVES-IRQ",
        "CHK-SYNC-ONLY-BIT-0",
        "CHK-SYNC-RESET-0",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sync_reg_irq_test_seq("sync_reg_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.rise_samples is not None and seq.fall_samples is not None, (
            f"the sequence published no poll counts "
            f"(rise={seq.rise_samples}, fall={seq.fall_samples})"
        )
        assert seq.accesses >= 9, f"only {seq.accesses} SEP_IN accesses issued, want >= 9"
