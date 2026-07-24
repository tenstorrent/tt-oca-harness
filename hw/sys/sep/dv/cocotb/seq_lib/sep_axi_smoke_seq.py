# SPDX-License-Identifier: Apache-2.0
"""Sequence for sep_axi_smoke_test.

Real AXI traffic over the CPU LSU bus (no booted CPU):
  1. Reset-value read of sep_cpu_ctrl.CLOCK_GATE_CTRL (decode sanity).
  2. Write -> readback of several pure-RW sep_cpu_ctrl scratch registers,
     each with a distinct pattern, to prove writes land and read back exactly.

Targets are RW registers with no hardware side effects and no external-memory
dependency (SEP_SW_DEBUG scratch + TIMEOUT_COUNT_* thresholds, which are inert
while TIMEOUT_ENABLE=0), so they exercise the write path without a memory model.
The scoreboard checks the AXI response and the read value for every access.
"""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

# sep_cpu_ctrl block base on the CPU-local map (CLOCK_GATE_CTRL @ +0x8 = 0x10A3_0008).
SEP_CPU_CTRL_BASE = 0x10A3_0000

CLOCK_GATE_CTRL_ADDR = SEP_CPU_CTRL_BASE + 0x008
CLOCK_GATE_CTRL_EXP = 0x001F_0021

# (name, addr, pattern) — pure 32-bit RW scratch/threshold registers.
WRITE_READBACK = [
    ("SEP_SW_DEBUG",         SEP_CPU_CTRL_BASE + 0x178, 0xDEAD_BEEF),
    ("TIMEOUT_COUNT_DMA",    SEP_CPU_CTRL_BASE + 0x028, 0x0BAD_C0DE),
    ("TIMEOUT_COUNT_SYS_IN", SEP_CPU_CTRL_BASE + 0x030, 0xCAFE_F00D),
    ("TIMEOUT_COUNT_MAILBOX_INBOUND", SEP_CPU_CTRL_BASE + 0x038, 0x1234_5678),
]


class sep_axi_smoke_seq(uvm_sequence):
    async def _read(self, addr: int, expected: int | None = None) -> None:
        item = SepAxiItem(f"rd_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)

    async def _write(self, addr: int, data: int) -> None:
        item = SepAxiItem(f"wr_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def body(self) -> None:
        # 1. Reset-value decode sanity.
        await self._read(CLOCK_GATE_CTRL_ADDR, expected=CLOCK_GATE_CTRL_EXP)

        # 2. Write -> readback across several RW registers (real write traffic).
        for _name, addr, pattern in WRITE_READBACK:
            await self._write(addr, pattern)
            await self._read(addr, expected=pattern)
