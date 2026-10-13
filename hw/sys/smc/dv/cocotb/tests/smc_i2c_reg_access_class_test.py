# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C register access classes on all three instances with both engines disabled."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_reg_access_class_test_seq import smc_i2c_reg_access_class_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_reg_access_class_test(smc_base_test):
    """Read-write patterns, access classes, I2C_CTRL fields and instance isolation."""

    required_evidence = (
        "CHK-I2C-RW-PATTERNS",
        "CHK-I2C-RW-FIELD-INDEP",
        "CHK-I2C-RW-PERSIST",
        "CHK-I2C-RW-OBSERVED",
        "CHK-I2C-RO-IGNORED",
        "CHK-I2C-ROWO-OBSERVED",
        "CHK-I2C-CTRL-FIELDS",
        "CHK-I2C-CTRL-NEIGHBOURS",
        "CHK-I2C-ISOLATION-MATRIX",
        "CHK-I2C-CTRL-NO-ENGINE",
        "CHK-NONVAC",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_reg_access_class_test_seq("i2c_reg_access_class_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
