# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Another device on SCL, at each point of an I2C controller transfer.

SCL pulled low early, SCL falling or both lines low around a control symbol,
SCL held across an expected rise, SCL held past the bus timeout, and a disable
while a repeated START is pending -- each placed by counting edges on the pads.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_scl_events_test_seq import (
    smc_i2c_controller_scl_events_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_scl_events_test(smc_base_test):
    """Another device on SCL, at each point of a controller transfer."""

    required_evidence = (
        "CHK-I2C-CTRL-BUS-TIMEOUT",
        "CHK-I2C-CTRL-PENDING-RESTART",
        "CHK-I2C-CTRL-SCL-INTERFERENCE",
        "CHK-I2C-CTRL-STRETCH-POINTS",
        "CHK-I2C-CTRL-SYMBOL-FAILED",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_scl_events_test_seq("i2c_controller_scl_events_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
