# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 wire timing on the instance-0 pads as a function of TIMING0-TIMING4.

The controller's phases are graded against THIGH, TLOW, T_R, T_F, THD_DAT, TSU_STA, THD_STA,
TSU_STO and T_BUF; TSU_DAT, whose effect the controller's bits do not show, is graded with I2C0
as a target.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_wire_timing_test_seq import smc_i2c_wire_timing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_wire_timing_test(smc_base_test):
    """Differences between programming sets on SCL and SDA equal the programmed differences."""

    required_evidence = (
        "CHK-I2C-WIRE-BUS-FREE-DELTA",
        "CHK-I2C-WIRE-DATA-HOLD-DELTA",
        "CHK-I2C-WIRE-DATA-SETUP-DELTA",
        "CHK-I2C-WIRE-MEASURED-ONLY",
        "CHK-I2C-WIRE-MIN-SET-RUN",
        "CHK-I2C-WIRE-NACK-HOLD-DELTA",
        "CHK-I2C-WIRE-RSTART-DELTA",
        "CHK-I2C-WIRE-SCL-HIGH-DELTA",
        "CHK-I2C-WIRE-SCL-LOW-DELTA",
        "CHK-I2C-WIRE-SCL-PERIOD-DELTA",
        "CHK-I2C-WIRE-STOP-SETUP-DELTA",
        "CHK-I2C-WIRE-TIMING-FIELDS",
        "CHK-I2C-WIRE-TRTF-DELTA",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 15

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_wire_timing_test_seq("i2c_wire_timing_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.wire_ok, "I2C wire timing scenario failed"
