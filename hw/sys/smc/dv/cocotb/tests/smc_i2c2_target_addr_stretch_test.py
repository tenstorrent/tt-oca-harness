# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C2 target clock stretching through the address phase of a repeated START.

A repeated START issued while the acquisition FIFO is full cannot be recorded,
so the target has to hold the bus until software drains it. Both settings of
CTRL.NACK_ADDR_AFTER_TIMEOUT are driven and the third leg makes the held
address phase a read, which needs a byte in TXDATA as well as the drain. No
stretch timeout is enabled, so software is the only way out of the hold.

One instance is driven per simulation; I2C0 and I2C1 have their own entries.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_addr_stretch_test_seq import smc_i2c_target_addr_stretch_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c2_target_addr_stretch_test(smc_base_test):
    """A repeated START against I2C2's full acquisition FIFO must hold the bus."""

    required_evidence = (
        "CHK-I2C2-TGT-ADDR-STRETCH",
        "CHK-I2C2-TGT-ADDR-STRETCH-NACK-MODE",
        "CHK-I2C2-TGT-ADDR-STRETCH-READ",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_addr_stretch_test_seq("i2c2_target_addr_stretch_seq", idx=2)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
