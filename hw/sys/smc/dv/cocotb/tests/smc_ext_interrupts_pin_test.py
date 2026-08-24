# SPDX-License-Identifier: Apache-2.0
"""ext_interrupts_i[0] through prim_sync3."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_ext_interrupts_pin_test_seq import smc_ext_interrupts_pin_test_seq


@pyuvm.test()
class smc_ext_interrupts_pin_test(smc_base_test):
    """ext_interrupts_i[0] after prim_sync3."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_interrupts_pin_test_seq("ext_irq0_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.rise_ok and seq.fall_ok, (
            f"ext irq0 incomplete idle={seq.idle_ok} "
            f"rise={seq.rise_ok} fall={seq.fall_ok}"
        )
