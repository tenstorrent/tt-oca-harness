# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS interrupt-observer UVM agent.

Passive agent. Samples the SMC sync interrupt output plus the OR-of-vector
GPIO and UART interrupt aggregates exposed at tb_top.
"""

from __future__ import annotations

import cocotb
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)

from .smc_irq_item import SmcIrqItem, SmcIrqOp


class SmcIrqDriver(uvm_driver):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.dut = None

    async def run_phase(self) -> None:
        self.dut = cocotb.top
        await self.cfg.reset_done.wait()
        self.logger.info("SMC IRQ observer driver ready")
        while True:
            item = await self.seq_item_port.get_next_item()
            if item.op is SmcIrqOp.SAMPLE:
                self._sample(item)
            else:
                raise ValueError(f"unsupported SmcIrqOp: {item.op}")
            self.ap.write(item)
            self.seq_item_port.item_done()

    def _sample(self, item: SmcIrqItem) -> None:
        dut = self.dut
        signals = {
            "sync_irq": dut.tb_sync_irq,
            "gpio_irq_any": dut.tb_gpio_irq_any,
            "uart_irq_any": dut.tb_uart_irq_any,
        }
        all_resolvable = True
        for attr, sig in signals.items():
            v = sig.value
            if v.is_resolvable:
                setattr(item, attr, int(v))
            else:
                all_resolvable = False
                setattr(item, attr, -1)
        item.resolvable = all_resolvable
        self.logger.info("Sampled %s", item)


class SmcIrqAgent(uvm_agent):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcIrqDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
