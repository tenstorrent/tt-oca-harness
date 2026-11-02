# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded I2C0 timing-set pairs: a larger TIMING field gives a longer measured pad interval."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_timing_set_rand_test_seq import smc_i2c_timing_set_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_timing_set_rand_test(smc_base_test):
    """Drawn base set and seven one-parameter pairs; six graded on order, the T_BUF one printed."""

    required_evidence = (
        "CHK-ITS-COMPLETE",
        "CHK-ITS-MIN-THIGH",
        "CHK-ITS-ORDER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_timing_set_rand_test_seq(
            "smc_i2c_timing_set_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "I2C timing set sequence did not complete"
