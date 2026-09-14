# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO wrap-0 edge IRQ types."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_p0_int_test_seq import smc_gpio_p0_int_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_p0_int_test(smc_base_test):
    """GPIO0 rising/falling edge IRQ via pad drive."""

    required_evidence = (
        "CHK-GPIO-P0-INT-BASIC",
        "CHK-GPIO-P0-INT-FALL",
        "CHK-GPIO-P0-INT-RISE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_p0_int_test_seq("gpio_p0_int_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.rising_ok and seq.falling_ok, (
            f"gpio p0 int incomplete rising={seq.rising_ok} falling={seq.falling_ok}"
        )
