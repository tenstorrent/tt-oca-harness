# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An unexpected START or STOP under the I2C controller.

An SDA edge inside an SCL high window is a control symbol. It is injected on a
chosen SCL pulse so it lands in a chosen part of the controller's bit loop,
four times across a write and a read.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_control_symbol_test_seq import (
    smc_i2c_controller_control_symbol_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_control_symbol_test(smc_base_test):
    """An unexpected START or STOP must be reported and the transfer dropped."""

    required_evidence = (
        "CHK-I2C-CTRL-SYMBOL-CLEAN",
        "CHK-I2C-CTRL-SYMBOL-UNSTABLE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_control_symbol_test_seq("i2c_controller_control_symbol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
