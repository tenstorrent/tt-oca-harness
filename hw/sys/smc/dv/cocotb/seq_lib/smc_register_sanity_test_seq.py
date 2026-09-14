# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_register_sanity_test.

Real AXI traffic on the **SEP_IN** fabric ingress port:
  * read reset value from SMC scratch registers,
  * write distinct patterns,
  * read back the exact values.

Access-port identity: the test starts this sequence on ``env.sys_axi_agent``,
whose driver is ``SmcSysAxiDriver`` with ``bus_prefix = "s_axi"`` /
``bus_name = "SEP_IN AXI"`` (``env/smc_sys_axi_agent.py``), and ``tb_top.sv``
wires the top-level ``s_axi_*`` pins into ``smc.sep_axi_in_req_i``. The
separate ``env.sys_in_axi_agent`` (``bus_prefix = "sys_axi"``) drives
``sys_axi_in_req_i``; this sequence never uses it.

What that does and does not prove: the scratch CSRs are internal to
``smc_misc_wrap`` and are reached over the same internal register fabric from
either ingress port, so the RW/reset-value proof below holds regardless of which
port carried it. It does NOT provide any coverage of the SYS_IN ingress port
itself -- its AXI handshake, decode, or filtering is untouched by this test.
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

        # The catalog entry validates the address AND carries the symbol-sourced
        # RDL reset value (``SCRATCH__SCRATCH__DATA_reset`` out of the generated
        # ``misc_wrap.h``). That value is what the reset read and the restore
        # write below compare against, so the compare moves with the RDL instead
        # of a hand-typed ``0`` ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
        targets = []
        for name, addr, pattern in WRITE_READBACK:
            entry = catalog_entry(name, addr, writable=True)
            assert entry.expected is not None, (
                f"{name}: the CSR field catalog carries no generated reset "
                "constant, so the reset read below would have no exact "
                "expectation to compare against"
            )
            targets.append((name, addr, pattern, entry.expected))

        for name, addr, _pattern, reset in targets:
            await self._read(name, addr, expected=reset)

        for name, addr, pattern, _reset in targets:
            await self._write(name, addr, pattern)
            await self._read(name, addr, expected=pattern)

        # Restore to the generated reset constant (not a literal 0), so the
        # closing readback re-proves the same RDL default the first read used.
        for name, addr, _pattern, reset in targets:
            await self._write(name, addr, reset)
            await self._read(name, addr, expected=reset)

        # Exact access count of this body (5 accesses per CSR); the fail-capable
        # floor is `min_csr_accesses` at the record_protocol_vip call in
        # tests/smc_register_sanity_test.py.
        assert self.accesses == 5 * len(WRITE_READBACK), (
            f"expected {5 * len(WRITE_READBACK)} real SEP_IN AXI CSR accesses, got {self.accesses}"
        )
