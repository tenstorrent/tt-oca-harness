# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The STOP the I2C0 controller makes when its enable is cleared mid-transaction.

Once parked with the format FIFO spent, and once halted on the NACK of an
address nobody answers -- the two open transactions the OpenTitan I2C theory
of operation says a cleared `CTRL.ENABLEHOST` ends with a STOP.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_disable_stop_test_seq import (
    smc_i2c_controller_disable_stop_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_disable_stop_test(smc_base_test):
    """Clear CTRL.ENABLEHOST with a transaction open, parked and halted on a NACK."""

    required_evidence = (
        "CHK-I2C-CTRL-DISABLE-STOP-HALTED",
        "CHK-I2C-CTRL-DISABLE-STOP-IDLE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_disable_stop_test_seq("i2c_controller_disable_stop_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
