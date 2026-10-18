# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C window answers under the i2c_cg_en clock gate and the state kept across it."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_clock_gate_response_test_seq import smc_i2c_clock_gate_response_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_clock_gate_response_test(smc_base_test):
    """Gate the I2C window, read the error answers, ungate and check what was kept."""

    required_evidence = (
        "CHK-I2C-GATE-GAP-OBS",
        "CHK-I2C-GATE-IRQ-OBS",
        "CHK-I2C-GATE-READ-SLVERR",
        "CHK-I2C-GATE-UNGATE-OKAY",
        "CHK-I2C-GATE-WRITE-SLVERR",
        "CHK-I2C-RETAIN-CYCLES",
        "CHK-I2C-RETAIN-GATED-WRITE-OBS",
        "CHK-I2C-RETAIN-INTR",
        "CHK-I2C-RETAIN-REGS",
        "CHK-NONVAC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_clock_gate_response_test_seq("i2c_clock_gate_response_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
