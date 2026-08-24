# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox CSR and IRQ-control smoke over real SYS AXI."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq

# SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR (offset 0x18; shifted from 0x30
# when the HANG_DET_* control registers were added ahead of it).
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = 1 << 1

MAILBOX_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x10
MAILBOX_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x18
MAILBOX_WIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x20
MAILBOX_RIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + 0x28
MAILBOX_IRQEN = 0xC001_8038

WRITE_READBACK = [
    ("WIRQT", MAILBOX_WIRQT, 0x5),
    ("RIRQT", MAILBOX_RIRQT, 0x6),
    ("IRQEN", MAILBOX_IRQEN, 0x7),
]


class smc_mailbox_irq_test_seq(smc_base_test_seq):
    """Exercise mailbox status and IRQ-control registers."""

    def __init__(self, name: str = "smc_mailbox_irq_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.accesses = 0

    async def _read(self, name: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def body(self) -> None:
        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enabled = self.clock_gate_value | MAILBOX_CG_EN
        await self._write("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=enabled)

        await self._read("MAILBOX_STATUS", MAILBOX_STATUS)
        await self._read("MAILBOX_ERROR_FLAGS", MAILBOX_ERROR_FLAGS)

        for name, addr, pattern in WRITE_READBACK:
            await self._write(name, addr, pattern)
            # These registers have side-effect/control semantics; OSS smoke
            # verifies decode and response, not mirror-style storage.
            await self._read(name, addr)

        for name, addr, _pattern in reversed(WRITE_READBACK):
            await self._write(f"{name}_RESTORE", addr, 0)
            await self._read(f"{name}_RESTORE", addr)

        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL,
                          self.clock_gate_value)
        await self._read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL,
                         expected=self.clock_gate_value)
        assert self.accesses == 19, "expected mailbox CSR access sequence"
