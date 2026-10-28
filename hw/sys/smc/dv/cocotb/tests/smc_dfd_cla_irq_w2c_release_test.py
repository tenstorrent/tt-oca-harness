# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt is released by the EapStatus W2C write.

Reproducer for #3389: with the pair that fired the debug-interrupt action
quiet, a single W2C write of its `CDbgEapStatus` bit must clear the status
and drop `cla_interrupt`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfd_cla_irq_w2c_release_test_seq import smc_dfd_cla_irq_w2c_release_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_cla_irq_w2c_release_test(smc_base_test):
    """Fire the debug-interrupt action, quiet the pair, write the W2C once, grade the line."""

    required_evidence = ("CHK-CLA-IRQ-W2C-RELEASE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_irq_w2c_release_test_seq("smc_dfd_cla_irq_w2c_release_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
