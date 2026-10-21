# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1 target ACK Control Mode with I2C2 as the controller, then the roles swapped.

Contract: SMC_I2C1_TARGET_ACK_CTRL in hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B3_VPLAN_DETAIL.md.
The three instances share one open-drain bus (+smc_i2c_shared_bus). Software reloads
TARGET_ACK_CTRL.NBYTES at each ACK-control hold, sweeps the field range on I2C1 and writes
TARGET_ACK_CTRL.NACK at a hold on each target instance.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c1_target_ack_ctrl_test_seq import smc_i2c1_target_ack_ctrl_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c1_target_ack_ctrl_test(smc_base_test):
    """A DUT target must ACK exactly NBYTES bytes per reload and NACK on request."""

    required_evidence = (
        "CHK-I2C1-ACKCTRL-DECREMENT",
        "CHK-I2C1-ACKCTRL-NACK-RECORD",
        "CHK-I2C1-ACKCTRL-NBYTES-RANGE",
        "CHK-I2C1-ACKCTRL-NBYTES3",
        "CHK-I2C1-ACKCTRL-RELOAD",
        "CHK-I2C1-ACKCTRL-SW-NACK",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c1_target_ack_ctrl_test_seq("i2c1_target_ack_ctrl_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
