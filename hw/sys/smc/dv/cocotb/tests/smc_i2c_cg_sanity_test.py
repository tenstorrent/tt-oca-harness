# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM I2C clock-gate sanity test.

Brings the SMC OSS top out of cold reset (handled by ``smc_base_test``), then
dispatches one observation sequence on the SMC I2C agent. The scoreboard
verifies that the top-level I2C observability signals are resolvable and that
the clock-gate enable matches the post-reset default.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_i2c_cg_sanity_test_seq import smc_i2c_cg_sanity_test_seq


@pyuvm.test()
class smc_i2c_cg_sanity_test(smc_base_test):
    """Run the SMC OSS I2C clock-gate sanity scenario."""

    async def run_scenario(self) -> None:
        seq = smc_i2c_cg_sanity_test_seq("i2c_cg_sanity_seq")
        await self.start_seq(seq)
