# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for sep_sram_smoke_test."""

from __future__ import annotations

import cocotb
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import sym

SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
STORE_PATTERN = 0x0123_4567_89AB_CDEF


class sep_sram_smoke_seq(uvm_sequence):
    def __init__(self, name: str = "sep_sram_smoke_seq") -> None:
        super().__init__(name)
        # (op, addr, response code) of every access, for OBS-RESP in the test.
        self.responses: list[tuple[str, int, int]] = []

    async def _check(self, chk: str, addr: int, length: int, expected: int, what: str) -> None:
        item = SepAxiItem(f"rd_sram_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.responses.append(("rd", addr, int(item.resp_code)))
        mask = (1 << (length * 8)) - 1
        got = item.rdata & mask
        assert got == expected & mask, (
            f"{chk} FAIL: {what}: read 0x{addr:08x} resp_ok={item.resp_ok} "
            f"got 0x{got:x} want 0x{expected & mask:x}"
        )
        cocotb.log.info("%s PASS: %s: read 0x%08x = 0x%016x", chk, what, addr, got)

    async def _pre_read(self, addr: int) -> None:
        item = SepAxiItem(f"rd_sram_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 8
        await self.start_item(item)
        await self.finish_item(item)
        self.responses.append(("rd", addr, int(item.resp_code)))
        fields = f"addr=0x{addr:08x} resp_ok={int(bool(item.resp_ok))} rdata=0x{item.rdata:016x}"
        if not (item.resp_ok and item.rdata != STORE_PATTERN):
            cocotb.log.error("CTRL-MISSING SRAM-PRE: %s", fields)
            raise AssertionError(f"CTRL-MISSING SRAM-PRE: {fields}")
        cocotb.log.info("CTRL-SRAM-PRE seen: %s", fields)

    async def _write(self, addr: int, data: int, length: int, size: int | None = None) -> None:
        item = SepAxiItem(f"wr_sram_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.size = size
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.responses.append(("wr", addr, int(item.resp_code)))

    async def body(self) -> None:
        base = SEP_SRAM_BASE + 0x100
        await self._pre_read(base)
        await self._write(base, STORE_PATTERN, 8)
        await self._check("CHK-STORE", base, 8, STORE_PATTERN, "64-bit write")
        # Drive a real 4-byte beat, not a full-width beat with narrowed strobes:
        # nothing else in the suite exercises a narrow AxSIZE on this bus.
        await self._write(base + 4, 0xFEED_FACE, 4, size=2)
        await self._check(
            "CHK-LANE", base, 8, 0xFEED_FACE_89AB_CDEF, "4-byte AxSIZE=2 write to the upper half"
        )
