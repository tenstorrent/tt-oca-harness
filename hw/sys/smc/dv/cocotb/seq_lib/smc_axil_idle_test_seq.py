# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_axil_idle_test."""

from __future__ import annotations

from env.smc_axil_item import SmcAxilItem, SmcAxilOp

from .smc_base_test_seq import smc_base_test_seq


class smc_axil_idle_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_axil_idle_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        item = SmcAxilItem("sample")
        item.op = SmcAxilOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
