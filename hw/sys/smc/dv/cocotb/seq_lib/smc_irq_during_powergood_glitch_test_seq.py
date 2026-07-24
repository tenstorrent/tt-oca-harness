# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_irq_during_powergood_glitch_test.

Samples IRQ before a powergood glitch and again after recovery. Verifies no
spurious IRQ fires due to the glitch / recovery.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from pyuvm import uvm_sequence

from env.smc_irq_item import SmcIrqItem, SmcIrqOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class _OneShot(uvm_sequence):
    def __init__(self, item, name: str = "one_shot") -> None:
        super().__init__(name)
        self._item = item

    async def body(self) -> None:
        await self.start_item(self._item)
        await self.finish_item(self._item)


class smc_irq_during_powergood_glitch_test_seq(smc_base_test_seq):

    GLITCH_REF_CYCLES = 8
    RECOVER_REF_CYCLES = 600

    def __init__(self, name: str = "smc_irq_during_powergood_glitch_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_irq = None
        self.baseline_irq = None
        self.recovered_irq = None

    async def body(self) -> None:
        dut = cocotb.top

        b = SmcIrqItem("irq_baseline")
        b.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(b)
        self.baseline_irq = b

        lo = SmcResetItem("pg_lo")
        lo.op = SmcResetOp.POWERGOOD_LO
        await self.dispatch_reset(lo)
        await ClockCycles(dut.clk_ref_i, self.GLITCH_REF_CYCLES)

        hi = SmcResetItem("pg_hi")
        hi.op = SmcResetOp.POWERGOOD_HI
        await self.dispatch_reset(hi)
        await ClockCycles(dut.clk_ref_i, self.RECOVER_REF_CYCLES)

        r = SmcIrqItem("irq_recovered")
        r.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(r)
        self.recovered_irq = r
