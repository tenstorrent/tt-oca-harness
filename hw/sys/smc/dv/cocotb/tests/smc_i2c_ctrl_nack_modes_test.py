# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller NACK reactions: read address, later data byte, NAKOK, handler timeout."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_ctrl_nack_modes_test_seq import smc_i2c_ctrl_nack_modes_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_ctrl_nack_modes_test(smc_base_test):
    """Drive NACKed transfers from the I2C0 controller and read the halt, event and wire state."""

    required_evidence = (
        "CHK-ADDR-NACK-READ",
        "CHK-DATA-NACK-LATER",
        "CHK-HALT-LEVEL",
        "CHK-NAKOK-CONTROL",
        "CHK-NAKOK-DATA",
        "CHK-NONVAC",
        "CHK-NTO-CLEAR-OBS",
        "CHK-NTO-DISABLED",
        "CHK-NTO-ENABLED",
        "CHK-STATUS-HALT-OBS",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_ctrl_nack_modes_test_seq("i2c_ctrl_nack_modes_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
