# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target handling of abandoned transactions and bare START/STOP symbols."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_bus_symbol_test_seq import smc_i2c_target_bus_symbol_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_bus_symbol_test(smc_base_test):
    """Early STOP, repeated START and read NACK, the detect flags and UNEXP_STOP."""

    required_evidence = (
        "CHK-I2C-TGT-ABANDON-LOG",
        "CHK-I2C-TGT-ABANDON-READ-NACK",
        "CHK-I2C-TGT-ABANDON-RECOVER",
        "CHK-I2C-TGT-DETECT-FLAGS",
        "CHK-I2C-TGT-DETECT-RACE-LOG",
        "CHK-I2C-TGT-REPSTART-ENTRIES",
        "CHK-I2C-TGT-UNEXP-STOP-LOG",
        "CHK-I2C-TGT-UNEXP-STOP-REG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_bus_symbol_test_seq("i2c_target_bus_symbol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
