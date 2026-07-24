# SPDX-License-Identifier: Apache-2.0
"""GPIO and IRQ representative CSR precheck."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = 0xC000_4000
GPIO_INPUT_ACTIVE_LOW_IRQ = (2 << 4) | (1 << 16) | (1 << 18) | (1 << 20)
MAILBOX_IRQEN = 0xC001_8038


class smc_gpio_irq_active_test_seq(SmcCsrSeq):
    """Precheck IRQ-control decode; GPIO IRQ behavior is verified by the VIP helper."""

    def __init__(self, name: str = "smc_gpio_irq_active_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_write("GPIO0_INPUT_ACTIVE_LOW_IRQ", GPIO0_DATA_CTRL,
                             GPIO_INPUT_ACTIVE_LOW_IRQ)
        await self.csr_read("MAILBOX_IRQEN_AS_IRQ_PROXY", MAILBOX_IRQEN, length=8)
        assert self.accesses == 2, "GPIO/IRQ precheck mismatch"
