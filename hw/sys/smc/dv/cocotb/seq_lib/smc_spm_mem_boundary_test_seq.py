# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
        # Words read back at each SPM edge; None until the leg runs.
        self.lo_ok: int | None = None
        self.mid_ok: int | None = None
        self.hi_ok: int | None = None

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        # CO-RESIDENCY, not per-address write-then-read.
        #
        # All three patterns are written first and read back afterwards.
        # Writing and reading one address at a time cannot see aliasing: if all
        # three "edge" addresses decoded onto ONE physical location, each write
        # would be followed immediately by its own read and every pair would
        # still match ([MERGED-EVIDENCE]). With the writes batched, a collapsed
        # decode returns the LAST pattern written and the first readback fails.
        assert len({p for _n, _a, p in _PATTERNS}) == len(_PATTERNS), (
            "SPM edge patterns are not pairwise distinct, so a co-resident "
            "readback could not discriminate the addresses"
        )
        assert len({a for _n, a, _p in _PATTERNS}) == len(_PATTERNS), (
            "SPM edge addresses are not pairwise distinct"
        )
        for name, addr, pattern in _PATTERNS:
            await self.csr_write(name, addr, pattern, length=8)
        observed = {}
        for name, addr, pattern in _PATTERNS:
            # `expected=` hands the compare to the scoreboard, which raises on
            # mismatch.
            observed[name] = await self.csr_read(name, addr, expected=pattern, length=8)
            cocotb.log.info(
                "CHK-SPM-MEM-%s: addr=0x%x data=0x%x (read while all %d edge "
                "patterns are resident)",
                name,
                addr,
                observed[name],
                len(_PATTERNS),
            )

        # `lo_ok`/`mid_ok`/`hi_ok` carry the measured words the BASIC token
        # prints ([NO-ALWAYS-PASS-CHECKER]).
        self.lo_ok, self.mid_ok, self.hi_ok = (
            observed["SPM_LO"],
            observed["SPM_LO_NEXT"],
            observed["SPM_HI"],
        )
        cocotb.log.info(
            "CHK-SPM-MEM-BASIC: lo@0x%x=0x%x next@0x%x=0x%x hi@0x%x=0x%x -- all "
            "three read back with the other two still resident, so a decode "
            "that collapsed the SPM edges onto one location fails here",
            _LO,
            self.lo_ok,
            _LO_NEXT,
            self.mid_ok,
            _HI,
            self.hi_ok,
        )

        # Reconcile the accesses the scoreboard saw against the count this body
        # constructs: 3 pattern writes + 3 readbacks. A body that stops after
        # the writes never reaches the three exact compares, so only this count
        # fails it.
        self.assert_all_reachable(len(_PATTERNS) * 2, "SPM_MEM_BOUNDARY")
