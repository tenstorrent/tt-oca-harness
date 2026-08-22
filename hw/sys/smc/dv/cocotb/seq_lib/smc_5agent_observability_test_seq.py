# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_5agent_observability_test.

Single scenario that samples all five agents (reset, i2c, clock, irq, gpio).
Verifies the full env composition: 5 agents, 5 item types, type-dispatched
scoreboard handling them all in one run.
"""

from __future__ import annotations

from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_gpio_item import SmcGpioItem, SmcGpioOp
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_irq_item import SmcIrqItem, SmcIrqOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_5agent_observability_test_seq(smc_base_test_seq):

    def __init__(self, name: str = "smc_5agent_observability_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_i2c = None
        self.dispatch_clk = None
        self.dispatch_irq = None
        self.dispatch_gpio = None

    async def body(self) -> None:
        r = SmcResetItem("reset"); r.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(r)

        i = SmcI2cItem("i2c"); i.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i)

        ir = SmcIrqItem("irq"); ir.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(ir)

        g = SmcGpioItem("gpio"); g.op = SmcGpioOp.SAMPLE
        await self.dispatch_gpio(g)

        c = SmcClkItem("clk"); c.op = SmcClkOp.COUNT_EDGES; c.window_ref_cycles = 25
        await self.dispatch_clk(c)
