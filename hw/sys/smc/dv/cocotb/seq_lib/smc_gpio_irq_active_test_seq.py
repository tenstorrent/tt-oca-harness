# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO and IRQ representative CSR precheck."""

from __future__ import annotations

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
GPIO_INPUT_ACTIVE_LOW_IRQ = (2 << 4) | (1 << 16) | (1 << 18) | (1 << 20)
MAILBOX_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")


class smc_gpio_irq_active_test_seq(SmcCsrSeq):
    """Precheck IRQ-control decode; GPIO IRQ behavior is verified by the VIP helper."""

    def __init__(self, name: str = "smc_gpio_irq_active_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_write(
            "GPIO0_INPUT_ACTIVE_LOW_IRQ", GPIO0_DATA_CTRL, GPIO_INPUT_ACTIVE_LOW_IRQ
        )
        await self.csr_read("MAILBOX_IRQEN_AS_IRQ_PROXY", MAILBOX_IRQEN, length=8)
        assert self.accesses == 2, "GPIO/IRQ precheck mismatch"
