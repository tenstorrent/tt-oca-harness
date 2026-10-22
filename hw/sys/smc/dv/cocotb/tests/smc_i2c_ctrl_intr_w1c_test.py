# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C controller and target interrupt and event write-one-clear lifecycle and enable gating."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_ctrl_intr_w1c_test_seq import smc_i2c_ctrl_intr_w1c_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_ctrl_intr_w1c_test(smc_base_test):
    """Set, clear and gate the instance 0 flags, then the I2C1/I2C2 interrupt and event legs."""

    required_evidence = (
        "CHK-CMDC-REASSERT",
        "CHK-CMDC-RS-OBS",
        "CHK-CMDC-STOP",
        "CHK-I2C12-CTRL-EVENTS-PARTIAL",
        "CHK-I2C12-CTRL-NACK-HALT",
        "CHK-I2C12-INTR-TEST-RW-HOLD",
        "CHK-I2C12-INTR-TEST-W1C",
        "CHK-I2C12-IRQ-LINE-GATE",
        "CHK-I2C12-SMBALERT",
        "CHK-I2C12-SMBSUS",
        "CHK-I2C12-TGT-ABNORMAL-END",
        "CHK-I2C12-TGT-TX-PENDING",
        "CHK-I2C12-UNEXP-STOP",
        "CHK-NONVAC",
        "CHK-SCLI-GATE",
        "CHK-SCLI-W1C",
        "CHK-SDAU-W1C",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 18

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_ctrl_intr_w1c_test_seq("i2c_ctrl_intr_w1c_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
