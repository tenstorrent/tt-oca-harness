# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An I2C target read ended by arbitration loss, and by a bus timeout.

SDA pulled low under a one the target is sending, and SCL held low past the
bus timeout while the target has a read to answer. Each raises its own
TARGET_EVENTS flag, which is then checked as a register.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_read_abort_test_seq import smc_i2c_target_read_abort_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_read_abort_test(smc_base_test):
    """A target read ended by arbitration loss, and by a bus timeout."""

    required_evidence = (
        "CHK-I2C-TGT-ARBITRATION-LOST",
        "CHK-I2C-TGT-EVENTS-RETAIN-ABORT",
        "CHK-I2C-TGT-READ-BUS-TIMEOUT",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_read_abort_test_seq("i2c_target_read_abort_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
