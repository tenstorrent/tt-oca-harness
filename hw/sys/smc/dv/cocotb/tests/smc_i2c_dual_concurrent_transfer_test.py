# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two concurrent I2C controller transfers on separate pad pairs."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_dual_concurrent_transfer_test_seq import (
    smc_i2c_dual_concurrent_transfer_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_dual_concurrent_transfer_test(smc_base_test):
    """Instances 0 and 1 write at the same time and each pad pair carries only its own transfer."""

    required_evidence = (
        "CHK-I2C-DUAL-CMD-COMPLETE",
        "CHK-I2C-DUAL-FIFO-LEVELS",
        "CHK-I2C-DUAL-LIVENESS",
        "CHK-I2C-DUAL-NACK-ISOLATION",
        "CHK-I2C-DUAL-PAD-ROUTE",
        "CHK-I2C-DUAL-REG-WINDOW",
        "CHK-I2C-DUAL-STOP-COUNT",
        "CHK-I2C-DUAL-TIMING-DIFF",
        "CHK-I2C-DUAL-WIRE-ORDER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_dual_concurrent_transfer_test_seq("i2c_dual_concurrent_transfer_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dual_ok, "I2C dual concurrent transfer scenario failed"
