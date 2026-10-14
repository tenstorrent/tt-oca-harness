# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C INTR_ENABLE and INTR_TEST through the instance outputs to peripheral and CPU interrupts."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_intr_output_path_test_seq import smc_i2c_intr_output_path_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_intr_output_path_test(smc_base_test):
    """INTR_ENABLE masking, one-hot raise, instance independence and the CPU vector bits."""

    required_evidence = (
        "CHK-I2C-CPU-NEIGHBOURS",
        "CHK-I2C-CPU-VEC-FALL-OBS",
        "CHK-I2C-CPU-VEC-RAISE-OBS",
        "CHK-I2C-ENABLE-MASK-OBS",
        "CHK-I2C-INSTANCE-INTR-ISOLATION",
        "CHK-I2C-IRQ-PERIPH-ONEHOT",
        "CHK-I2C-IRQ-RESET-LOW",
        "CHK-I2C-IRQ-THREE-INDEPENDENT",
        "CHK-I2C-PAIR-MASK",
        "CHK-NONVAC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_intr_output_path_test_seq("i2c_intr_output_path_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
