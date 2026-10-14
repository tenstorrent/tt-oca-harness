# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C window decode, reset state, unclaimed-gap response and aligned access."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_window_decode_test_seq import smc_i2c_window_decode_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_window_decode_test(smc_base_test):
    """Reads and writes the three I2C instance blocks, I2C_CTRL and the gap from SEP_IN."""

    required_evidence = (
        "CHK-I2C-ACCESS-ALIGNED",
        "CHK-I2C-CTRL-RESET",
        "CHK-I2C-DECODE-ALTERNATE",
        "CHK-I2C-DECODE-IDENTITY",
        "CHK-I2C-GAP-NO-SIDE-EFFECT",
        "CHK-I2C-GAP-READ-DECERR",
        "CHK-I2C-RESERVED-OBS",
        "CHK-I2C-RESET-LITERALS",
        "CHK-I2C-RESET-SIDE-OBS",
        "CHK-I2C-RESET-STATUS",
        "CHK-NONVAC",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_window_decode_test_seq("i2c_window_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
