# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical reset recovery matrix sequence.

This sequence compresses the reset-depth variants into one coverage-oriented
scenario: baseline sample, powergood glitch, cold-reset reassert, cool-reset
pulse, and final recovery sample.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_reset_recovery_matrix_test_seq(smc_base_test_seq):
    """Exercise the canonical reset/powergood recovery matrix."""

    POWERGOOD_GLITCH_REF_CYCLES = 8
    COLD_REASSERT_REF_CYCLES = 40
    COOL_ASSERT_REF_CYCLES = 80
    RECOVER_REF_CYCLES = 700

    def __init__(self, name: str = "smc_reset_recovery_matrix_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcResetItem] = []
        self.raw_samples: list[SmcResetItem] = []

    async def _send(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await self.start_item(item)
        await self.finish_item(item)
        if op is SmcResetOp.SAMPLE:
            self.samples.append(item)
        elif op is SmcResetOp.RAW_SAMPLE:
            self.raw_samples.append(item)
        return item

    async def _raw_after(self, cycles: int) -> SmcResetItem:
        await ClockCycles(cocotb.top.clk_ref_i, cycles)
        return await self._send(SmcResetOp.RAW_SAMPLE)

    async def _recover_and_sample(self) -> SmcResetItem:
        await ClockCycles(cocotb.top.clk_ref_i, self.RECOVER_REF_CYCLES)
        return await self._send(SmcResetOp.SAMPLE)

    async def body(self) -> None:
        dut = cocotb.top

        await self._send(SmcResetOp.SAMPLE)

        await self._send(SmcResetOp.POWERGOOD_LO)
        await self._raw_after(2)
        await self._raw_after(max(self.POWERGOOD_GLITCH_REF_CYCLES - 2, 1))
        await self._send(SmcResetOp.POWERGOOD_HI)
        for offset in (2, 8, 20, 45, 120):
            await ClockCycles(dut.clk_ref_i, offset)
            await self._send(SmcResetOp.RAW_SAMPLE)
        await self._recover_and_sample()

        await self._send(SmcResetOp.COLD_RST_LO)
        await self._raw_after(4)
        await ClockCycles(dut.clk_ref_i, self.COLD_REASSERT_REF_CYCLES - 4)
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._raw_after(8)
        await self._raw_after(32)
        await self._recover_and_sample()

        await self._send(SmcResetOp.COOL_RST_LO)
        await self._raw_after(8)
        await ClockCycles(dut.clk_ref_i, self.COOL_ASSERT_REF_CYCLES - 8)
        await self._send(SmcResetOp.COOL_RST_HI)
        await self._raw_after(16)
        await self._recover_and_sample()

        assert len(self.samples) == 4, "expected baseline plus 3 recovery samples"
        assert self.raw_samples, "expected RAW_SAMPLE coverage during reset transitions"
        assert all(sample.resolvable for sample in self.raw_samples), (
            "unresolved reset matrix raw sample"
        )
