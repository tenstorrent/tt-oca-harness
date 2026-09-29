# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 CTRL writes landed on the cycle a bus-monitor or target event fires."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_window_landing_test_seq import smc_i2c_window_landing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_window_landing_test(smc_base_test):
    """Land CTRL writes on bus-monitor and target event cycles."""

    required_evidence = (
        "CHK-I2C-MONITOR-DISABLE-AT-DETECT",
        "CHK-I2C-NACK-AND-BUS-TIMEOUT",
        "CHK-I2C-TARGET-DISABLE-AT-STOP",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_window_landing_test_seq("smc_i2c_window_landing_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
