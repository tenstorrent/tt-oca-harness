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

# OTBN STATUS code, from the value table in the otbn.rdl STATUS description.
# The post-reset internal secure wipe; the no_cpu smoke never brings EDN up,
# so OTBN stays in this state for the whole leaf.
OTBN_STATUS_BUSY_SEC_WIPE_INT = ot_rdl_table_code("otbn", "STATUS", "BUSY_SEC_WIPE_INT")

# OTBN IMEM/DMEM are 32-bit SECDED words and reject a 64-bit beat with SLVERR, so
# every access here drives size=2 (4-byte beat) -- the same width SepOtbn's
# inherited _wr/_rd use for the real program load. Leaving size unset lets
# cocotbext-axi pick the full 64-bit bus width, which exercises an access no OTBN
# driver in this environment ever issues and which the memories reject.
_AXI_SIZE_4B = 2


def _resp(item: SepAxiItem) -> int:
    """The transaction's AXI response code, or -1 when none was returned."""
    return item.resp_list[-1] if item.resp_list else -1


class sep_otbn_mem_smoke_seq(uvm_sequence):
    """IMEM and DMEM write/readback while OTBN STATUS reads BUSY_SEC_WIPE_INT.

    The OTBN register text states that while OTBN is busy a memory read
    returns 0, a write is ignored and the access raises ILLEGAL_BUS_ACCESS. No
    SEP text states whether that holds during the post-reset internal wipe, so
    the memory accesses are not graded: the scoreboard does not judge their
    response codes or read data, and the test logs them. A timed-out access
    still fails the leaf.
    """

    async def _access(
        self, op: SepAxiOp, addr: int, data: int = 0, *, graded: bool = False
    ) -> SepAxiItem:
        item = SepAxiItem(f"{op.value}_otbn_0x{addr:08x}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.size = _AXI_SIZE_4B
        item.wdata = data
        item.allow_unverified_write_resp = not graded
        item.allow_ungraded_read_resp = not graded
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def _check_mem_access_precondition(self) -> None:
        """Read STATUS once and require the state the log-only accesses describe.

        CTRL-OTBN-MEM-PRECOND requires the STATUS status field to be
        BUSY_SEC_WIPE_INT; any other value logs CTRL-MISSING and fails the
        leaf, so a configuration that reaches another state is not logged as
        this one. The STATUS read is a register access, and the scoreboard
        grades its response OKAY.
        """
        item = await self._access(SepAxiOp.READ, OTBN_ADDR_STATUS, graded=True)
        self.status_raw = item.rdata
        st = self.status_raw & OTBN_STATUS_MASK
        fields = (
            f"status=0x{self.status_raw:08x} status_code=0x{st:02x} "
            f"expect=0x{OTBN_STATUS_BUSY_SEC_WIPE_INT:02x}"
        )
        if st != OTBN_STATUS_BUSY_SEC_WIPE_INT:
            cocotb.log.error("CTRL-MISSING OTBN-MEM-PRECOND: %s", fields)
            raise AssertionError(f"CTRL-MISSING OTBN-MEM-PRECOND: {fields}")
        cocotb.log.info("CTRL-OTBN-MEM-PRECOND seen: %s", fields)

    async def _write_read(self, addr: int, data: int) -> tuple[int, int, int]:
        wr = await self._access(SepAxiOp.WRITE, addr, data)
        rd = await self._access(SepAxiOp.READ, addr)
        return _resp(wr), _resp(rd), rd.rdata & 0xFFFF_FFFF

    async def body(self) -> None:
        await self._check_mem_access_precondition()
        self.imem = await self._write_read(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        self.dmem = await self._write_read(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
