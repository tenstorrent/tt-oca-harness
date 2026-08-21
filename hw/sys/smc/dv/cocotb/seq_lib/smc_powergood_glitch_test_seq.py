# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_powergood_glitch_test.

Exercises the SMC powergood stretcher: sample baseline, drive powergood low for
a few cycles (glitch), drive it high, wait for the 32-cycle stretcher + reset
chain to recover, sample again. The scoreboard verifies both samples report
all primary resets released and powergood_stable high.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_powergood_glitch_test_seq(smc_base_test_seq):

    GLITCH_DURATION_REF_CYCLES = 8
    RECOVER_WAIT_REF_CYCLES = 500

    def __init__(self, name: str = "smc_powergood_glitch_test_seq") -> None:
        super().__init__(name)
        self.baseline_sample: SmcResetItem | None = None
        self.recovered_sample: SmcResetItem | None = None

    async def _send(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value)
        item.op = op
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def body(self) -> None:
        dut = cocotb.top
        self.baseline_sample = await self._send(SmcResetOp.SAMPLE)

        await self._send(SmcResetOp.POWERGOOD_LO)
        # Mid-glitch snapshots: capture reset-state diversity while resets are
        # asserted (scoreboard records but does not assert post-stable values).
        await ClockCycles(dut.clk_ref_i, 2)
        await self._send(SmcResetOp.RAW_SAMPLE)
        await ClockCycles(dut.clk_ref_i, max(self.GLITCH_DURATION_REF_CYCLES - 2, 1))
        await self._send(SmcResetOp.RAW_SAMPLE)
        await self._send(SmcResetOp.POWERGOOD_HI)
        # Finer-grained recovery sampling. The stretcher releases bits over a
        # span of ~32 cycles; sample early/mid/late to maximise transition
        # state coverage in the (powergood, cold_stable, primary_ref, primary_smc)
        # space.
        already_waited = 0
        for offset in (1, 3, 5, 8, 12, 16, 22, 30, 45, 70, 120):
            delta = offset - already_waited
            if delta > 0:
                await ClockCycles(dut.clk_ref_i, delta)
                already_waited = offset
            await self._send(SmcResetOp.RAW_SAMPLE)
        tail = self.RECOVER_WAIT_REF_CYCLES - already_waited
        if tail > 0:
            await ClockCycles(dut.clk_ref_i, tail)

        self.recovered_sample = await self._send(SmcResetOp.SAMPLE)
