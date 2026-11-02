# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The I2C0 bus-free time after a STOP follows the programmed TIMING4.T_BUF.

Reproducer: `i2c.rdl` TIMING4.T_BUF "specifies the time between a STOP and START condition
(t_BUF) in system clock cycles", so every bus-free time, from the STOP SDA rise to the START SDA
fall of the transfer queued behind it, must be at least the programmed `T_BUF` and must move the
way `T_BUF` moved. With `THD_DAT` 25 to 32 the controller starts the next transfer after
`T_R + TSU_STA + 7` cycles whatever `T_BUF` holds. The `smc_i2c_timing_set_rand_test` draw runs
first: its six graded pairs, in order, are the arm leg that shows the measurer follows a field
change before the `T_BUF` pair is graded.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_timing_set_rand_test_seq import smc_i2c_timing_set_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_tbuf_bus_free_test(smc_base_test):
    """The I2C timing-set draw with the bus-free time of the T_BUF pair graded."""

    required_evidence = (
        "CHK-ITS-COMPLETE",
        "CHK-ITS-MIN-THIGH",
        "CHK-ITS-ORDER",
        "CHK-ITS-TBUF-BUS-FREE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_timing_set_rand_test_seq(
            "smc_i2c_timing_set_rand_test_seq",
            seed=self.random_seed(),
            grade_tbuf_bus_free=True,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "I2C timing set sequence did not complete"
