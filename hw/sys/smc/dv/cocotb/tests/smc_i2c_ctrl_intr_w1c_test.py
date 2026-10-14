# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller interrupt write-one-clear lifecycle and enable gating."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_ctrl_intr_w1c_test_seq import smc_i2c_ctrl_intr_w1c_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_ctrl_intr_w1c_test(smc_base_test):
    """Set, clear and gate CMD_COMPLETE, SDA_UNSTABLE and SCL_INTERFERENCE on instance 0."""

    required_evidence = (
        "CHK-CMDC-REASSERT",
        "CHK-CMDC-RS-OBS",
        "CHK-CMDC-STOP",
        "CHK-NONVAC",
        "CHK-SCLI-GATE",
        "CHK-SCLI-W1C",
        "CHK-SDAU-W1C",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_ctrl_intr_w1c_test_seq("i2c_ctrl_intr_w1c_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
