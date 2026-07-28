# SPDX-License-Identifier: Apache-2.0
"""Sequence for sep_otbn_mem_smoke_test."""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

OTBN_IMEM_BASE = 0x1090_4000
OTBN_DMEM_BASE = 0x1090_8000
OTBN_IMEM_SMOKE_WORD = 0x0000_0013
OTBN_DMEM_SMOKE_WORD = 0xA5A5_5A5A


class sep_otbn_mem_smoke_seq(uvm_sequence):
    async def _write(self, addr: int, data: int, length: int = 4) -> None:
        item = SepAxiItem(f"wr_otbn_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        item.allow_unverified_write_resp = True
        await self.start_item(item)
        await self.finish_item(item)

    async def _read(self, addr: int, expected: int, length: int = 4) -> None:
        item = SepAxiItem(f"rd_otbn_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)

    async def body(self) -> None:
        await self._write(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        await self._read(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        await self._write(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
        await self._read(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
