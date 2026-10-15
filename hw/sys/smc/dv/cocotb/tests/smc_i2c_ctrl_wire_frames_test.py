# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller FIFO stream decoded bit for bit on the open-drain bus."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_ctrl_wire_frames_test_seq import smc_i2c_ctrl_wire_frames_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_ctrl_wire_frames_test(smc_base_test):
    """Plain writes, STOP placement, address values, reads and queueing while busy on I2C0."""

    required_evidence = (
        "CHK-ADDR-VALUES",
        "CHK-HOSTIDLE-OBS",
        "CHK-NONVAC",
        "CHK-ONE-START-PER-STOP",
        "CHK-QUEUE-WHILE-BUSY",
        "CHK-READ-COUNTS",
        "CHK-READ-LAST-NACK",
        "CHK-RX-POP",
        "CHK-STOP-POSITION",
        "CHK-TIMEOUT-PATHS",
        "CHK-WRITE-PATTERN",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_ctrl_wire_frames_test_seq("i2c_ctrl_wire_frames_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
