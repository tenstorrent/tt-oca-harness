# SPDX-License-Identifier: Apache-2.0
"""SPM window edges via SEP_IN AXI. Real-stall / multi-hart traffic is not claimed."""

from __future__ import annotations

import cocotb

from .smc_addr_map import SPM_MEMORY_BASE, SPM_MEMORY_SIZE
from .smc_csr_seq_utils import SmcCsrSeq

# 64-bit aligned edges of the PeakRDL SPM window.
_LO = SPM_MEMORY_BASE
_LO_NEXT = SPM_MEMORY_BASE + 8
_HI = SPM_MEMORY_BASE + SPM_MEMORY_SIZE - 8

_PATTERNS = (
    ("SPM_LO", _LO, 0xA5A5_5A5A_C006_0000),
    ("SPM_LO_NEXT", _LO_NEXT, 0x5A5A_A5A5_C006_0008),
    ("SPM_HI", _HI, 0xF00D_BEEF_C006_FFF8),
)


class smc_spm_mem_boundary_test_seq(SmcCsrSeq):
    """Write/readback SPM first, second, and last 64-bit words."""

    def __init__(self, name: str = "smc_spm_mem_boundary_test_seq") -> None:
        super().__init__(name)
        self.lo_ok = False
        self.mid_ok = False
        self.hi_ok = False

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        flags = []
        for name, addr, pattern in _PATTERNS:
            await self.csr_write(name, addr, pattern, length=8)
            got = await self.csr_read(name, addr, expected=pattern, length=8)
            assert got == pattern, f"{name} @0x{addr:08x} got 0x{got:x} want 0x{pattern:x}"
            flags.append(True)
            cocotb.log.info("CHK-SPM-MEM-%s: addr=0x%x data=0x%x", name, addr, got)

        self.lo_ok, self.mid_ok, self.hi_ok = flags
        cocotb.log.info(
            "CHK-SPM-MEM-BASIC: lo=%s next=%s hi=%s",
            self.lo_ok,
            self.mid_ok,
            self.hi_ok,
        )
