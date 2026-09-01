# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_register_sanity_test (Batch B).

Real SYS AXI traffic through ``smc.sys_axi_in_req_i``:
  * read reset value from SMC scratch registers,
  * write distinct patterns,
  * read back the exact values.
"""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_field_catalog import catalog_entry

SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_COLD_1 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)
SCRATCH_COLD_WARM_0 = smc_indexed_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0
)

WRITE_READBACK = [
    ("SCRATCH_COLD_0", SCRATCH_COLD_0, 0xA5A5_0001),
    ("SCRATCH_COLD_1", SCRATCH_COLD_1, 0x5A5A_0002),
    ("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, 0xC0DE_0003),
]


class smc_register_sanity_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_register_sanity_test_seq") -> None:
        super().__init__(name)
        self.accesses = 0

    async def _read(self, name: str, addr: int, expected: int | None = None) -> None:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for name, addr, _pattern in WRITE_READBACK:
            catalog_entry(name, addr, writable=True)

        for name, addr, _pattern in WRITE_READBACK:
            await self._read(name, addr, expected=0)

        for name, addr, pattern in WRITE_READBACK:
            await self._write(name, addr, pattern)
            await self._read(name, addr, expected=pattern)

        for name, addr, _pattern in WRITE_READBACK:
            await self._write(name, addr, 0)
            await self._read(name, addr, expected=0)

        assert self.accesses == 15, "expected 15 real SYS AXI CSR accesses"
