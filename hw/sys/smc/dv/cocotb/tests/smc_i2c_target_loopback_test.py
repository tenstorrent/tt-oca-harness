# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target-mode line loopback against a full transmit FIFO, then I2C1 line controls on its pads."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_loopback_test_seq import smc_i2c_target_loopback_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_loopback_test(smc_base_test):
    """Loop back a target with a full transmit FIFO, then run the I2C1 line-control legs."""

    required_evidence = (
        "CHK-I2C-TGT-LOOPBACK-BLOCKED",
        "CHK-I2C-TGT-LOOPBACK-ECHO",
        "CHK-I2C1-LLPBK-ECHO",
        "CHK-I2C1-LLPBK-OFF",
        "CHK-I2C1-OVRD-PADS",
        "CHK-I2C1-OVRD-VAL",
        "CHK-I2C1-RX-OVERFLOW",
        "CHK-I2C1-RXRST",
        "CHK-I2C1-SCL-INTERFERENCE",
        "CHK-I2C1-SDA-UNSTABLE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_loopback_test_seq("i2c_target_loopback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
