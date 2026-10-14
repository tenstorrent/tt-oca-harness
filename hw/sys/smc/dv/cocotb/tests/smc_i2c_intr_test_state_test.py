# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C INTR_TEST forcing INTR_STATE: status release, event latch, partial clears, isolation."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_intr_test_state_test_seq import smc_i2c_intr_test_state_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_intr_test_state_test(smc_base_test):
    """INTR_TEST writes read back through INTR_STATE with every INTR_ENABLE left at reset."""

    required_evidence = (
        "CHK-I2C-EVENT-NO-RELEASE",
        "CHK-I2C-EVENT-PARTIAL-CLEAR",
        "CHK-I2C-EVENT-REARM",
        "CHK-I2C-STATUS-FORCE",
        "CHK-I2C-STATUS-LIVE-OBS",
        "CHK-I2C-STATUS-RELEASE",
        "CHK-I2C-STATUS-SW-RO",
        "CHK-I2C-W1C-ISOLATION",
        "CHK-NONVAC",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_intr_test_state_test_seq("i2c_intr_test_state_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
