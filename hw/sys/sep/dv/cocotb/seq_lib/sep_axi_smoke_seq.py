# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import SEP_CPU_CTRL, sym

SEP_CPU_CTRL_BASE = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")

# Non-zero reset value, so a successful read proves the block actually decoded
# rather than returning zeros from an unmapped address.
LOCAL_BASE_ADDR_ADDR = SEP_CPU_CTRL.addr("SEP_LOCAL_BASE_ADDR")
LOCAL_BASE_ADDR_EXP = SEP_CPU_CTRL.reset32("SEP_LOCAL_BASE_ADDR")

# (name, addr, pattern, implemented-field mask)
WRITE_READBACK = [
    (
        "SEP_SW_DEBUG",
        SEP_CPU_CTRL.addr("SEP_SW_DEBUG"),
        0xDEAD_BEEF,
        SEP_CPU_CTRL.mask32("SEP_SW_DEBUG"),
    ),
    # nmi_vec is [31:1]; bit 0 is reserved and reads back as zero.
    (
        "SEP_NMI_VEC",
        SEP_CPU_CTRL.addr("SEP_NMI_VEC"),
        0x0BAD_C0DE,
        SEP_CPU_CTRL.mask32("SEP_NMI_VEC"),
    ),
    (
        "PKA_CTRL",
        SEP_CPU_CTRL.addr("PKA_CTRL"),
        0x0000_0007,
        SEP_CPU_CTRL.mask32("PKA_CTRL"),
    ),
    (
        "SEP_REGION_SIZE",
        SEP_CPU_CTRL.addr("SEP_REGION_SIZE"),
        0x0200_0000,
        SEP_CPU_CTRL.mask32("SEP_REGION_SIZE"),
    ),
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
