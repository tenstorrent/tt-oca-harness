# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two endings of an I2C controller transaction that no leaf produced.

A read whose last byte carries no stop, and a NACK left unhandled until
HOST_NACK_HANDLER_TIMEOUT runs out -- which is also where CONTROLLER_EVENTS is
checked as a register that clears only on a written one.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_exits_test_seq import smc_i2c_controller_exits_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_exits_test(smc_base_test):
    """A read that continues, and a NACK left unhandled."""

    required_evidence = (
        "CHK-I2C-CTRL-EVENTS-RETAIN",
        "CHK-I2C-CTRL-NACK-TIMEOUT",
        "CHK-I2C-CTRL-READ-256",
        "CHK-I2C-CTRL-READ-CONTINUES",
        "CHK-I2C-CTRL-READ-RCONT",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_exits_test_seq("i2c_controller_exits_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
