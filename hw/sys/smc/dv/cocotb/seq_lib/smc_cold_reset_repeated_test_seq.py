# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_cold_reset_repeated_test (3 re-asserts)."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_cold_reset_repeated_test_seq(smc_base_test_seq):
    REASSERT_REF_CYCLES = 40
    BETWEEN_REF_CYCLES = 200
    RECOVER_REF_CYCLES = 700

    async def _send(self, op):
        i = SmcResetItem(op.value)
        i.op = op
        await self.start_item(i)
        await self.finish_item(i)
        return i

    async def body(self) -> None:
        dut = cocotb.top
        await self._send(SmcResetOp.SAMPLE)
        for _ in range(3):
            await self._send(SmcResetOp.COLD_RST_LO)
            # Mid-assertion RAW_SAMPLE: cold reset active, primary outputs low.
            await ClockCycles(dut.clk_ref_i, 4)
            await self._send(SmcResetOp.RAW_SAMPLE)
            await ClockCycles(dut.clk_ref_i, self.REASSERT_REF_CYCLES - 4)
            await self._send(SmcResetOp.COLD_RST_HI)
            # Recovery RAW_SAMPLEs across the stretcher window.
            waited = 0
            for off in (2, 8, 20, 40):
                delta = off - waited
                await ClockCycles(dut.clk_ref_i, delta)
                waited = off
                await self._send(SmcResetOp.RAW_SAMPLE)
            await ClockCycles(dut.clk_ref_i, max(self.BETWEEN_REF_CYCLES - waited, 1))
        await ClockCycles(dut.clk_ref_i, self.RECOVER_REF_CYCLES)
        await self._send(SmcResetOp.SAMPLE)
        # Exercise the cool-reset op set so the scoreboard sees the full reset_op range.
        await self._send(SmcResetOp.COOL_RST_LO)
        await ClockCycles(dut.clk_ref_i, self.REASSERT_REF_CYCLES)
        await self._send(SmcResetOp.COOL_RST_HI)
        await ClockCycles(dut.clk_ref_i, self.RECOVER_REF_CYCLES)
        await self._send(SmcResetOp.SAMPLE)
