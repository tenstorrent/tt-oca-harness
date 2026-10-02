# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target, bus monitor, wrapper decode and SCL pad ownership at their edges."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_bus_corners_test_seq import smc_i2c_bus_corners_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_bus_corners_test(smc_base_test):
    """Unexpected STOP, an inapplicable NACK, bus-free SCL, wrapper decode, pad ownership."""

    required_evidence = (
        "CHK-I2C-BUS-FREE-SCL",
        "CHK-I2C-PAD-LSIO-DISABLE",
        "CHK-I2C-TGT-NACK-IGNORED",
        "CHK-I2C-TGT-UNEXP-STOP",
        "CHK-I2C-WRAP-PAST-CTRL",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_bus_corners_test_seq("i2c_bus_corners_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
