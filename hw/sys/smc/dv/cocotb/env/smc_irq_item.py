# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS interrupt observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item

IRQ_SAMPLE_FIELDS = ("sync_irq", "gpio_irq_any", "uart_irq_any")


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
        # --- Optional exact expectations (None => the idle default 0) --------
        # An idle "all IRQs low" sample is a negative check: it also passes on a
        # stuck-at-0 / unwired probe. Set expect_<field>=1 on the leg whose
        # source the sequence has just asserted to give the same probe a
        # positive control ([NEGATIVE-NEEDS-POSITIVE-CONTROL]), then re-sample
        # with the default to prove it returns to idle.
        self.expect_sync_irq: int | None = None
        self.expect_gpio_irq_any: int | None = None
        self.expect_uart_irq_any: int | None = None

    def expected(self, field: str) -> int:
        """Expected value for `field`: the item's override, else idle 0."""
        exp = getattr(self, "expect_" + field)
        return 0 if exp is None else exp

    def __str__(self) -> str:
        return (
            f"SmcIrqItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"sync={self.sync_irq}, gpio_any={self.gpio_irq_any}, "
            f"uart_any={self.uart_irq_any})"
        )
