# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM interrupt-observe test.

DV-CARD:          SMC_007   ANCHOR: smc_irq_observe_test
DV-CARD-REVISION: 3   RECORD-SHA256: a399ea1cc087130bcc95d3c95962fb1940e9e59cb611bea4b2b536edd3ef47ff
DV-CARD-SOURCE:   hw/sys/smc/dv/tb/SMC_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_irq_observe_test_seq import smc_irq_observe_test_seq


@pyuvm.test()
class smc_irq_observe_test(smc_base_test):

    async def run_scenario(self) -> None:
        seq = smc_irq_observe_test_seq("irq_observe_seq")
        await self.start_seq(seq, self.env.irq_agent.sequencer)
