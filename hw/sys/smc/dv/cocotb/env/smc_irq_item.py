# SPDX-License-Identifier: Apache-2.0
"""Transaction items for the SMC OSS interrupt observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcIrqOp(Enum):
    SAMPLE = "SAMPLE"


class SmcIrqItem(uvm_sequence_item):

    def __init__(self, name: str = "SmcIrqItem") -> None:
        super().__init__(name)
        self.op: SmcIrqOp = SmcIrqOp.SAMPLE
        self.sync_irq: int = -1
        self.gpio_irq_any: int = -1
        self.uart_irq_any: int = -1
        self.resolvable: bool = False

    def __str__(self) -> str:
        return (
            f"SmcIrqItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"sync={self.sync_irq}, gpio_any={self.gpio_irq_any}, "
            f"uart_any={self.uart_irq_any})"
        )
