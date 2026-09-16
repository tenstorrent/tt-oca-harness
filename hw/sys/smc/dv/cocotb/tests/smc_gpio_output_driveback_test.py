# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS GPIO register-driven output (core2pad) driveback test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_output_driveback_test_seq import (
    smc_gpio_output_driveback_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_output_driveback_test(smc_base_test):
    """Program GPIO wrap 0 as TX output and check the DUT pad outputs."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_output_driveback_test_seq("gpio_output_driveback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
