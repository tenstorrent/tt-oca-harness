# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_i2c_cg_sanity_test.

Dispatches one SmcI2cItem SAMPLE transaction. The agent driver reads
``tb_i2c_cg_en`` / ``tb_i2c_debug_lo`` and broadcasts the result; the
scoreboard checks resolvability and the post-reset clock-gate default.
"""

from __future__ import annotations

from env.smc_i2c_item import SmcI2cItem, SmcI2cOp

from .smc_base_test_seq import smc_base_test_seq


class smc_i2c_cg_sanity_test_seq(smc_base_test_seq):
    """Run the SMC OSS I2C clock-gate sanity scenario."""

    def __init__(self, name: str = "smc_i2c_cg_sanity_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        item = SmcI2cItem("sample")
        item.op = SmcI2cOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
