# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO pad-edge-to-interrupt latency on drawn pads, and detection with readback unselected."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_irq_latency_test_seq import smc_gpio_irq_latency_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_irq_latency_test(smc_base_test):
    """Every pad edge reaches tb_gpio_interrupt after the synchronizer plus one register."""

    required_evidence = (
        "CHK-GPIO-IRQ-LATENCY",
        "CHK-GPIO-IRQ-WITHOUT-READBACK",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_irq_latency_test_seq("smc_gpio_irq_latency_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
