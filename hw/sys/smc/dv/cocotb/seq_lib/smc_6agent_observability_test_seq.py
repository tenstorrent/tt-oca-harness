# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_6agent_observability_test.

All six agents (reset / i2c / clk / irq / gpio / axil) sampled in one scenario.
The ultimate full-env demonstration.
"""

from __future__ import annotations

from env.smc_axil_item import SmcAxilItem, SmcAxilOp
from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_gpio_item import SmcGpioItem, SmcGpioOp
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_irq_item import SmcIrqItem, SmcIrqOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_6agent_observability_test_seq(smc_base_test_seq):

    def __init__(self, name: str = "smc_6agent_observability_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_i2c = None
        self.dispatch_clk = None
        self.dispatch_irq = None
        self.dispatch_gpio = None
        self.dispatch_axil = None

    async def body(self) -> None:
        r = SmcResetItem("reset"); r.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(r)
        i = SmcI2cItem("i2c"); i.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i)
        ir = SmcIrqItem("irq"); ir.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(ir)
        g = SmcGpioItem("gpio"); g.op = SmcGpioOp.SAMPLE
        await self.dispatch_gpio(g)
        a = SmcAxilItem("axil"); a.op = SmcAxilOp.SAMPLE
        await self.dispatch_axil(a)
        c = SmcClkItem("clk"); c.op = SmcClkOp.COUNT_EDGES; c.window_ref_cycles = 25
        await self.dispatch_clk(c)
