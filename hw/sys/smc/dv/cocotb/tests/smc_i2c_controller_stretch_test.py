# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The I2C controller waiting out a held clock.

Another device on the open-drain bus holds SCL low part-way through the DUT
controller's transfer, at several points across it. Each transfer must run
longer by about the hold and still deliver every byte.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_stretch_test_seq import smc_i2c_controller_stretch_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_stretch_test(smc_base_test):
    """The controller must wait out a held clock and finish the transfer."""

    required_evidence = (
        "CHK-I2C-CTRL-STRETCH-CLEAN",
        "CHK-I2C-CTRL-STRETCH-HELD",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_stretch_test_seq("i2c_controller_stretch_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
