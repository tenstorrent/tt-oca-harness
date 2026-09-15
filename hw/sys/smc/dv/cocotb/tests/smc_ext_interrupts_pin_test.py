# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ext_interrupts_i[0] through prim_sync3."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_interrupts_pin_test_seq import smc_ext_interrupts_pin_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_interrupts_pin_test(smc_base_test):
    """ext_interrupts_i[0] after prim_sync3."""

    required_evidence = (
        "CHK-EXT-IRQ0-BASIC",
        "CHK-EXT-IRQ0-FALL",
        "CHK-EXT-IRQ0-IDLE",
        "CHK-EXT-IRQ0-RISE",
        "CHK-EXT-IRQ0-WARM",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_interrupts_pin_test_seq("ext_irq0_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.rise_ok and seq.fall_ok, (
            f"ext irq0 incomplete idle={seq.idle_ok} rise={seq.rise_ok} fall={seq.fall_ok}"
        )
