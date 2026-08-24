# SPDX-License-Identifier: Apache-2.0
"""GPIO wrap-0 edge IRQ types."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_gpio_p0_int_test_seq import smc_gpio_p0_int_test_seq


@pyuvm.test()
class smc_gpio_p0_int_test(smc_base_test):
    """GPIO0 rising/falling edge IRQ via pad drive."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_p0_int_test_seq("gpio_p0_int_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.rising_ok and seq.falling_ok, (
            f"gpio p0 int incomplete rising={seq.rising_ok} falling={seq.falling_ok}"
        )
