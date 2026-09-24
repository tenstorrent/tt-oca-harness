# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C target ACK Control Mode: accepting and rejecting bytes mid-transfer.

With CTRL.ACK_CTRL_EN set the target stretches once its ACK count is spent and
waits for software to reload TARGET_ACK_CTRL.NBYTES or to write
TARGET_ACK_CTRL.NACK. Both answers are given, on transfers whose acquisition
FIFO has room throughout.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_ack_ctrl_test_seq import smc_i2c_target_ack_ctrl_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_ack_ctrl_test(smc_base_test):
    """Software must be able to accept or refuse bytes while the target holds."""

    required_evidence = (
        "CHK-I2C-TGT-ACK-CTRL-ACCEPT",
        "CHK-I2C-TGT-ACK-CTRL-NACK",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_ack_ctrl_test_seq("i2c_target_ack_ctrl_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
