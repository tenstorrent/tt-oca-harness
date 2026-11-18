# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded I2C bus matrix: address pair, role, instance pairs, NACK position and ACK control."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_bus_matrix_rand_test_seq import smc_i2c_bus_matrix_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_bus_matrix_rand_test(smc_base_test):
    """Drawn addresses, pairs, lengths and NACK positions on the shared three-instance bus."""

    required_evidence = (
        "CHK-IBM-ACKCTRL",
        "CHK-IBM-ADDR",
        "CHK-IBM-NAKOK",
        "CHK-IBM-PAIR",
        "CHK-IBM-ROLE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_bus_matrix_rand_test_seq(
            "smc_i2c_bus_matrix_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "I2C bus matrix sequence did not complete"
