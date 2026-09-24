# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Coincident SCL and SDA edges, and SCL falls after a stretch, inside I2C0 controller transfers."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_controller_edge_timing_test_seq import (
    smc_i2c_controller_edge_timing_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_edge_timing_test(smc_base_test):
    """Edges that land together or after a stretch, at chosen points of a transfer."""

    required_evidence = (
        "CHK-I2C-CTRL-EDGE-FALL-CHANGE",
        "CHK-I2C-CTRL-EDGE-FIRST-START",
        "CHK-I2C-CTRL-EDGE-RISE-CHANGE",
        "CHK-I2C-CTRL-EDGE-STOP-HOLD",
        "CHK-I2C-CTRL-EDGE-STRETCH-FALL",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_edge_timing_test_seq("i2c_controller_edge_timing_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
