# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target transmit path: TXDATA reads, automatic TX stretch and software TX stretch."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_tx_read_test_seq import smc_i2c_target_tx_read_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_tx_read_test(smc_base_test):
    """The bench controller reads bytes software loaded into the I2C0 target TX FIFO."""

    required_evidence = (
        "CHK-I2C-TGT-TX-READ-ORDER",
        "CHK-I2C-TGT-TX-READ-RESIDUE",
        "CHK-I2C-TGT-TX-AUTO-STRETCH",
        "CHK-I2C-TGT-TX-AUTO-MIDREAD-LOG",
        "CHK-I2C-TGT-TX-TXRST-STRETCH-LOG",
        "CHK-I2C-TGT-TX-TXRST-RECOVER",
        "CHK-I2C-TGT-TX-SW-STRETCH",
        "CHK-I2C-TGT-TX-SW-RESET-RELOAD",
        "CHK-I2C-TGT-TX-SW-RACE-LOG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_tx_read_test_seq("i2c_target_tx_read_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
