# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The STOP the I2C0 controller makes when its enable is cleared mid-transaction.

Once parked in IDLE with the format FIFO spent, and once on the single cycle
the controller spends in POP_FMT_FIFO between two entries, found by bisection on
when the disable is written.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_disable_stop_test_seq import (
    smc_i2c_controller_disable_stop_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_disable_stop_test(smc_base_test):
    """Clear CTRL.ENABLEHOST with a transaction open, in IDLE and in POP_FMT_FIFO."""

    required_evidence = (
        "CHK-I2C-CTRL-DISABLE-STOP-IDLE",
        "CHK-I2C-CTRL-DISABLE-STOP-POP",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_disable_stop_test_seq("i2c_controller_disable_stop_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
