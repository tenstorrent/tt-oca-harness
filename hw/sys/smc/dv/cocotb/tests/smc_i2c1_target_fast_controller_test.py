# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1 target refusing a controller that clocks faster than its hold time.

The target waits out TIMING3.THD_DAT with SCL low before it acknowledges. A
controller that releases SCL first is abandoned, at the address acknowledge
and at a data acknowledge; transfers at the slow rate before and after are the
control.

One instance is driven per simulation; I2C0 and I2C2 have their own entries.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_fast_controller_test_seq import (
    smc_i2c_target_fast_controller_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c1_target_fast_controller_test(smc_base_test):
    """A controller faster than I2C1's hold time must be refused."""

    required_evidence = (
        "CHK-I2C1-TGT-FAST-CTRL-ADDR",
        "CHK-I2C1-TGT-FAST-CTRL-CONTROL",
        "CHK-I2C1-TGT-FAST-CTRL-DATA",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_fast_controller_test_seq("i2c1_target_fast_controller_seq", idx=1)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
