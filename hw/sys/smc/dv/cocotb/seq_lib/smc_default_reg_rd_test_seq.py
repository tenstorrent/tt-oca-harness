# SPDX-License-Identifier: Apache-2.0
"""Default register read smoke over real SYS AXI.

This is the OSS-safe slice of the legacy default-reg-read flow: it reads
side-effect-free internal SMC CSRs through ``sys_axi_in_req_i`` and checks
that every selected address returns an OKAY AXI response.
"""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_field_catalog import catalog_entry

READABLE_REGS = [
    ("SCRATCH_COLD_0", 0xC000_2800, 0x0000_0000),
    ("SCRATCH_COLD_1", 0xC000_2804, 0x0000_0000),
    ("SCRATCH_COLD_WARM_0", 0xC000_2880, 0x0000_0000),
    ("CHIP_CONFIG_VERSION_LO", 0xC000_2900, None),
    ("CHIP_CONFIG_VERSION_HI", 0xC000_2904, None),
    ("CHIP_CONFIG_CHIP_ID", 0xC000_2908, None),
]


class smc_default_reg_rd_test_seq(smc_base_test_seq):
    """Read a compact set of side-effect-free SMC CSRs."""

    def __init__(self, name: str = "smc_default_reg_rd_test_seq") -> None:
        super().__init__(name)
        self.reads = 0

    async def _read(self, name: str, addr: int, expected: int | None) -> None:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.reads += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for name, addr, expected in READABLE_REGS:
            catalog_entry(name, addr, writable=name.startswith("SCRATCH_"))
            await self._read(name, addr, expected)
        assert self.reads == len(READABLE_REGS), "default-reg read sweep did not run"
