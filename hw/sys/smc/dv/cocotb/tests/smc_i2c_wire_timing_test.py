# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller wire timing on the instance-0 pads as a function of TIMING0-TIMING4."""

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
        "CHK-I2C-WIRE-DATA-SETUP-MEASURED",
        "CHK-I2C-WIRE-MEASURED-ONLY",
        "CHK-I2C-WIRE-MIN-SET-RUN",
        "CHK-I2C-WIRE-NACK-HOLD-DELTA",
        "CHK-I2C-WIRE-RSTART-DELTA",
        "CHK-I2C-WIRE-SCL-HIGH-DELTA",
        "CHK-I2C-WIRE-SCL-LOW-DELTA",
        "CHK-I2C-WIRE-SCL-PERIOD-DELTA",
        "CHK-I2C-WIRE-STOP-SETUP-DELTA",
        "CHK-I2C-WIRE-TIMING-FIELDS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 14

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_wire_timing_test_seq("i2c_wire_timing_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.wire_ok, "I2C wire timing scenario failed"
