# SPDX-License-Identifier: Apache-2.0
"""Sequence for sep_sram_smoke_test."""

from __future__ import annotations

from sep_reg_meta import sym

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")


class sep_sram_smoke_seq(uvm_sequence):
    async def _read(self, addr: int, length: int, expected: int | None = None) -> None:
        item = SepAxiItem(f"rd_sram_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)

    async def _write(self, addr: int, data: int, length: int) -> None:
        item = SepAxiItem(f"wr_sram_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def body(self) -> None:
        base = SEP_SRAM_BASE + 0x100
        await self._read(base, 8, expected=0)
        await self._write(base, 0x0123_4567_89AB_CDEF, 8)
        await self._read(base, 8, expected=0x0123_4567_89AB_CDEF)
        await self._write(base + 4, 0xFEED_FACE, 4)
        await self._read(base, 8, expected=0xFEED_FACE_89AB_CDEF)
