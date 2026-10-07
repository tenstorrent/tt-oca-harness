# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Six format-queue shapes of the I2C0 controller.

A NACK allowed by NAKOK, two transactions queued together, a park that
continues, a NACK left pending across a disable, controller-mode loopback and
a receive FIFO nobody drains.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_queue_shapes_test_seq import (
    smc_i2c_controller_queue_shapes_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_queue_shapes_test(smc_base_test):
    """Six format-queue shapes against the bench EEPROM target."""

    required_evidence = (
        "CHK-I2C-CTRL-BACK-TO-BACK",
        "CHK-I2C-CTRL-LOOPBACK-HOST",
        "CHK-I2C-CTRL-NACK-DISABLED",
        "CHK-I2C-CTRL-NAKOK",
        "CHK-I2C-CTRL-PARK-CONTINUE",
        "CHK-I2C-CTRL-RX-OVERFLOW",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_queue_shapes_test_seq("i2c_controller_queue_shapes_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
