# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An unexpected START or STOP under the I2C controller.

An SDA edge inside an SCL high window is a control symbol. It is injected on a
chosen SCL pulse, four times across a write and a read: in two pulses the
controller receives, where it must report `SDA_UNSTABLE`, and in two it drives
high itself, where it must report `SDA_INTERFERENCE`.
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
        "CHK-I2C-CTRL-SYMBOL-INTERFERENCE",
        "CHK-I2C-CTRL-SYMBOL-UNSTABLE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_control_symbol_test_seq("i2c_controller_control_symbol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
