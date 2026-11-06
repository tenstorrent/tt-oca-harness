# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for sep_otbn_mem_smoke_test."""

from __future__ import annotations

import cocotb
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_spec_tables import ot_rdl_table_code
from pyuvm import uvm_sequence
from sep_reg_meta import OTBN, sym

OTBN_BASE = sym("OTBN_REG_MAP_BASE_ADDR")
OTBN_ADDR_STATUS = OTBN.addr("STATUS")
OTBN_STATUS_MASK = OTBN.field_mask("STATUS", "status")
OTBN_IMEM_BASE = sym("OTBN_IMEM_MEM_BASE_ADDR")
OTBN_DMEM_BASE = sym("OTBN_DMEM_MEM_BASE_ADDR")
OTBN_IMEM_SMOKE_WORD = 0x0000_0013
OTBN_DMEM_SMOKE_WORD = 0xA5A5_5A5A

# OTBN STATUS codes, from the value table in the otbn.rdl STATUS description.
OTBN_STATUS_BUSY_EXECUTE = ot_rdl_table_code("otbn", "STATUS", "BUSY_EXECUTE")
OTBN_STATUS_LOCKED = ot_rdl_table_code("otbn", "STATUS", "LOCKED")

# The state in which a bus access to IMEM/DMEM is illegal. While STATUS
# is BusyExecute, a host request is diverted and latches illegal_bus_access.
OTBN_MEM_ACCESS_ILLEGAL_STATES = (OTBN_STATUS_BUSY_EXECUTE,)

# OTBN IMEM/DMEM are 32-bit SECDED words and reject a 64-bit beat with SLVERR, so
# every access here drives size=2 (4-byte beat) -- the same width SepOtbn's
# inherited _wr/_rd use for the real program load. Leaving size unset lets
# cocotbext-axi pick the full 64-bit bus width, which exercises an access no OTBN
# driver in this environment ever issues and which the memories reject.
_AXI_SIZE_4B = 2


class sep_otbn_mem_smoke_seq(uvm_sequence):
    async def _write(self, addr: int, data: int, length: int = 4) -> None:
        item = SepAxiItem(f"wr_otbn_0x{addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.size = _AXI_SIZE_4B
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)

    async def _read(self, addr: int, expected: int | None = None, length: int = 4) -> int:
        item = SepAxiItem(f"rd_otbn_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = length
        item.size = _AXI_SIZE_4B
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def _check_mem_access_precondition(self) -> None:
        """Read STATUS once before the memory accesses and grade the bench state.

        CTRL-OTBN-MEM-PRECOND requires the STATUS status field to be neither
        LOCKED nor BUSY_EXECUTE; otherwise it logs CTRL-MISSING and fails the
        leaf. OBS-OTBN-MEM-STATUS logs the raw STATUS word and the status field.
        It is logged, not graded: no authored text states whether IMEM/DMEM
        accept a bus access in the state that the field reports here.
        """
        raw = await self._read(OTBN_ADDR_STATUS)
        st = raw & OTBN_STATUS_MASK
        locked = int(st == OTBN_STATUS_LOCKED)
        executing = int(st in OTBN_MEM_ACCESS_ILLEGAL_STATES)
        fields = f"status=0x{raw:08x} locked={locked} executing={executing}"
        if locked or executing:
            cocotb.log.error("CTRL-MISSING OTBN-MEM-PRECOND: %s", fields)
            raise AssertionError(f"CTRL-MISSING OTBN-MEM-PRECOND: {fields}")
        cocotb.log.info("CTRL-OTBN-MEM-PRECOND seen: %s", fields)
        cocotb.log.info("OBS-OTBN-MEM-STATUS status=0x%08x status_code=0x%02x", raw, st)

    async def body(self) -> None:
        await self._check_mem_access_precondition()
        await self._write(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        self.imem_rdata = await self._read(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        await self._write(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
        self.dmem_rdata = await self._read(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
