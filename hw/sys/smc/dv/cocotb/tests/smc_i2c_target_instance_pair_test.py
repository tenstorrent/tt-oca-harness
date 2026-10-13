# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Instance pairs on the shared I2C bus: isolation, interrupts, clock gate and NACK handler."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_instance_pair_test_seq import smc_i2c_target_instance_pair_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_instance_pair_test(smc_base_test):
    """Pairs of wrapper instances on one bus, the I2C clock gate and the NACK handler."""

    required_evidence = (
        "CHK-I2C-TGT-INSTANCE-IRQ",
        "CHK-I2C-TGT-INSTANCE-ISOLATION",
        "CHK-I2C-TGT-INSTANCE-CONTENTION-LOG",
        "CHK-I2C-TGT-LOOP-PAIRS",
        "CHK-I2C-TGT-CG-GATED",
        "CHK-I2C-TGT-CG-UNGATE",
        "CHK-I2C-TGT-CG-MIDXFER",
        "CHK-I2C-TGT-NACKH-STOP",
        "CHK-I2C-TGT-NACKH-LOG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_instance_pair_test_seq("i2c_target_instance_pair_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
