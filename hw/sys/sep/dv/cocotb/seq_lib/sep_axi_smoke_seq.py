# SPDX-License-Identifier: Apache-2.0
"""Sequence for sep_axi_smoke_test.

Real AXI traffic over the CPU LSU bus (no booted CPU):
  1. Reset-value read of sep_cpu_ctrl.SEP_LOCAL_BASE_ADDR (decode sanity).
  2. Write -> readback of several RW sep_cpu_ctrl registers, each with a
     distinct pattern, to prove writes land and read back exactly.

Targets are RW registers with no hardware side effects and no external-memory
dependency, so they exercise the write path without a memory model. Several are
narrower than 32 bits, so each carries the mask of its implemented field bits.
The scoreboard checks the AXI response and the read value for every access.

Offsets and reset values follow the generated map
(hw/sys/sep/regs/gen/py/sep_reg.py, SEP_CPU_CTRL_*).
"""

from __future__ import annotations

from sep_reg_meta import sym

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

SEP_CPU_CTRL_BASE = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")

# Non-zero reset value, so a successful read proves the block actually decoded
# rather than returning zeros from an unmapped address.
LOCAL_BASE_ADDR_ADDR = SEP_CPU_CTRL_BASE + 0x0C8
LOCAL_BASE_ADDR_EXP = 0xD000_0000

# (name, addr, pattern, implemented-field mask)
WRITE_READBACK = [
    ("SEP_SW_DEBUG",  SEP_CPU_CTRL_BASE + 0x178, 0xDEAD_BEEF, 0xFFFF_FFFF),
    # nmi_vec is [31:1]; bit 0 is reserved and reads back as zero.
    ("SEP_NMI_VEC",   SEP_CPU_CTRL_BASE + 0x180, 0x0BAD_C0DE, 0xFFFF_FFFE),
    ("RAS_BANK_INFO", SEP_CPU_CTRL_BASE + 0x170, 0x0000_00A5, 0x0000_00FF),
    ("PKA_CTRL",      SEP_CPU_CTRL_BASE + 0x020, 0x0000_0007, 0x0000_0007),
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
        await self._read(LOCAL_BASE_ADDR_ADDR, expected=LOCAL_BASE_ADDR_EXP)

        # 2. Write -> readback across several RW registers (real write traffic).
        for _name, addr, pattern, mask in WRITE_READBACK:
            await self._write(addr, pattern)
            await self._read(addr, expected=pattern & mask)
