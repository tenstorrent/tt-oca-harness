# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C instance-to-instance read, target-side STOP interrupt and per-instance interrupt lines."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_ctrl_xinst_events_test_seq import smc_i2c_ctrl_xinst_events_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_ctrl_xinst_events_test(smc_base_test):
    """One controller at a time on the shared bus against a DUT target, then the irq lines."""

    required_evidence = (
        "CHK-XINST-READ-1-2",
        "CHK-XINST-UNCFG-OBS",
        "CHK-UNEXP-STOP-OBS",
        "CHK-UNEXP-CLEAR-OBS",
        "CHK-UNEXP-NORMAL-OBS",
        "CHK-IRQ-CMDC-LINES",
        "CHK-IRQ-HALT-LINES",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_ctrl_xinst_events_test_seq("i2c_ctrl_xinst_events_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
