# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PVT temp interrupt via ext_interrupts_i[1] (no dedicated pin)."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_temp_interrupt_test_seq import smc_temp_interrupt_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_temp_interrupt_test(smc_base_test):
    """Digital temp IRQ pin; analog PVT macros not claimed."""

    required_evidence = (
        "CHK-TEMP-IRQ-BASIC",
        "CHK-TEMP-IRQ-FALL",
        "CHK-TEMP-IRQ-IDLE",
        "CHK-TEMP-IRQ-RISE",
        "CHK-TEMP-IRQ-WARM",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_temp_interrupt_test_seq("temp_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.rise_ok and seq.fall_ok, (
            f"temp irq incomplete idle={seq.idle_ok} rise={seq.rise_ok} fall={seq.fall_ok}"
        )
