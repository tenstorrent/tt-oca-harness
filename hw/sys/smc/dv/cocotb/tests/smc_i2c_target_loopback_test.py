# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target-mode line loopback against a full transmit FIFO."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_loopback_test_seq import smc_i2c_target_loopback_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_loopback_test(smc_base_test):
    """Write to a looped-back target with a full transmit FIFO, then read everything back."""

    required_evidence = (
        "CHK-I2C-TGT-LOOPBACK-BLOCKED",
        "CHK-I2C-TGT-LOOPBACK-ECHO",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_loopback_test_seq("i2c_target_loopback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
