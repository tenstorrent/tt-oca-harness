# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt holds through the W2C and releases once EnableEap is cleared.

With the pair that fired the debug-interrupt action quiet, a W2C write of its
`CDbgEapStatus` bit with `EnableEap` set clears the status and holds
`cla_interrupt`; clearing `EnableEap` and writing the W2C bit releases it, and
setting `EnableEap` again leaves it released (#3389, the documented sequence).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfd_cla_irq_w2c_release_test_seq import smc_dfd_cla_irq_w2c_release_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_cla_irq_w2c_release_test(smc_base_test):
    """Fire the debug-interrupt action, then grade the hold and the documented release."""

    required_evidence = ("CHK-CLA-IRQ-EAP-RELEASE", "CHK-CLA-IRQ-W2C-HOLD")
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_irq_w2c_release_test_seq("smc_dfd_cla_irq_w2c_release_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
