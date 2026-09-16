# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for sep_otbn_mem_smoke_test."""

from __future__ import annotations

import cocotb
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import OTBN, sym

OTBN_BASE = sym("OTBN_REG_MAP_BASE_ADDR")
OTBN_ADDR_STATUS = OTBN.addr("STATUS")
OTBN_IMEM_BASE = sym("OTBN_IMEM_MEM_BASE_ADDR")
OTBN_DMEM_BASE = sym("OTBN_DMEM_MEM_BASE_ADDR")
OTBN_IMEM_SMOKE_WORD = 0x0000_0013
OTBN_DMEM_SMOKE_WORD = 0xA5A5_5A5A

# OTBN STATUS encoding, from the generated otbn.adoc STATUS field.
OTBN_STATUS_BUSY_EXECUTE = 0x01
OTBN_STATUS_LOCKED = 0xFF

# The state in which a bus access to IMEM/DMEM is illegal. While STATUS
# is BusyExecute, a host request is diverted and latches illegal_bus_access.
# The BusySecWipe*mem encodings are not that case: a scramble-key request
# is outstanding and the bus still reaches the SRAM.
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
        """Establish, from the DUT, that an IMEM/DMEM readback compare is meaningful.

        OTBN comes out of reset into StatusBusySecWipeInt (0x04) and stays there for
        this test: leaving it needs EDN entropy to reseed URND, and the no_cpu smoke
        configuration never brings EDN up. That is harmless here -- the internal wipe
        does not touch IMEM/DMEM, which is why every access below completes OKAY.

        What would NOT be harmless is OTBN executing, which makes a bus access to
        these memories illegal, or OTBN LOCKED, which fails accesses outright. Both
        are checked rather than assumed, so this test fails loudly if OTBN's reset
        behaviour ever changes.
        """
        st = await self._read(OTBN_ADDR_STATUS) & 0xFF
        assert st != OTBN_STATUS_LOCKED, f"OTBN LOCKED (STATUS=0x{st:02x}) before memory smoke"
        assert st not in OTBN_MEM_ACCESS_ILLEGAL_STATES, (
            f"OTBN is executing (STATUS=0x{st:02x}); a bus access to IMEM/DMEM would "
            f"be diverted and flagged as an illegal bus access"
        )
        cocotb.log.info(
            "OTBN memory-access precondition OK: STATUS=0x%08x (not LOCKED, not executing)",
            st,
        )

    async def body(self) -> None:
        await self._check_mem_access_precondition()
        await self._write(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        await self._read(OTBN_IMEM_BASE, OTBN_IMEM_SMOKE_WORD)
        await self._write(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
        await self._read(OTBN_DMEM_BASE, OTBN_DMEM_SMOKE_WORD)
