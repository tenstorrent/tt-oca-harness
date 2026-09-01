# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical high-density SMC smoke sequence.

This sequence combines the six-agent observability smoke with the reset recovery
matrix so one canonical test covers the already-public Batch A surface.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_axil_item import SmcAxilItem, SmcAxilOp
from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_gpio_item import SmcGpioItem, SmcGpioOp
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_irq_item import SmcIrqItem, SmcIrqOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_canonical_smoke_test_seq(smc_base_test_seq):
    """Exercise all public smoke agents across reset recovery events."""

    POWERGOOD_GLITCH_REF_CYCLES = 8
    COLD_REASSERT_REF_CYCLES = 40
    COOL_ASSERT_REF_CYCLES = 80
    RECOVER_REF_CYCLES = 700

    def __init__(self, name: str = "smc_canonical_smoke_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_i2c = None
        self.dispatch_clk = None
        self.dispatch_irq = None
        self.dispatch_gpio = None
        self.dispatch_axil = None
        self.multi_agent_samples = 0
        self.raw_reset_samples = 0

    async def _reset(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await self.dispatch_reset(item)
        if op is SmcResetOp.RAW_SAMPLE:
            self.raw_reset_samples += 1
        return item

    async def _sample_all(self, label: str) -> None:
        reset = SmcResetItem(f"{label}_reset")
        reset.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(reset)

        i2c = SmcI2cItem(f"{label}_i2c")
        i2c.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i2c)

        irq = SmcIrqItem(f"{label}_irq")
        irq.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(irq)

        gpio = SmcGpioItem(f"{label}_gpio")
        gpio.op = SmcGpioOp.SAMPLE
        await self.dispatch_gpio(gpio)

        axil = SmcAxilItem(f"{label}_axil")
        axil.op = SmcAxilOp.SAMPLE
        await self.dispatch_axil(axil)

        clk = SmcClkItem(f"{label}_clk")
        clk.op = SmcClkOp.COUNT_EDGES
        clk.window_ref_cycles = 25
        await self.dispatch_clk(clk)

        self.multi_agent_samples += 1

    async def _raw_after(self, cycles: int) -> None:
        await ClockCycles(cocotb.top.clk_ref_i, cycles)
        await self._reset(SmcResetOp.RAW_SAMPLE)

    async def _recover_and_sample_all(self, label: str) -> None:
        await ClockCycles(cocotb.top.clk_ref_i, self.RECOVER_REF_CYCLES)
        await self._sample_all(label)

    async def body(self) -> None:
        dut = cocotb.top

        await self._sample_all("baseline")

        await self._reset(SmcResetOp.POWERGOOD_LO)
        await self._raw_after(2)
        await self._raw_after(max(self.POWERGOOD_GLITCH_REF_CYCLES - 2, 1))
        await self._reset(SmcResetOp.POWERGOOD_HI)
        await self._raw_after(8)
        await self._raw_after(32)
        await self._recover_and_sample_all("after_powergood")

        await self._reset(SmcResetOp.COLD_RST_LO)
        await self._raw_after(4)
        await ClockCycles(dut.clk_ref_i, self.COLD_REASSERT_REF_CYCLES - 4)
        await self._reset(SmcResetOp.COLD_RST_HI)
        await self._raw_after(8)
        await self._raw_after(32)
        await self._recover_and_sample_all("after_cold")

        await self._reset(SmcResetOp.COOL_RST_LO)
        await self._raw_after(8)
        await ClockCycles(dut.clk_ref_i, self.COOL_ASSERT_REF_CYCLES - 8)
        await self._reset(SmcResetOp.COOL_RST_HI)
        await self._raw_after(16)
        await self._recover_and_sample_all("after_cool")

        assert self.multi_agent_samples == 4, "expected baseline plus 3 recovery sweeps"
        assert self.raw_reset_samples >= 7, "expected reset transition RAW_SAMPLE coverage"
