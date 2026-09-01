# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM interrupt-observe test.

DV-CARD:          SMC_007   ANCHOR: smc_irq_observe_test
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_observe_test_seq import smc_irq_observe_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_observe_test(smc_base_test):
    async def run_scenario(self) -> None:
        seq = smc_irq_observe_test_seq("irq_observe_seq")
        await self.start_seq(seq, self.env.irq_agent.sequencer)
