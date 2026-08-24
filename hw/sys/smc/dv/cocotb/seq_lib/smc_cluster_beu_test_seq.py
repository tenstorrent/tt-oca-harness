# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap Round 4: SMC cluster BEU sweep (TC_SMC_P1CG_21).

RTL exposes one Bus Error Unit (BEU) per core at 0xC801_0000 + core*0x1000
(4 cores). Each BEU carries CAUSE / PHYS_ADDR / ENABLE / PLIC_ENABLE /
ACCRUED_ENABLE / LOCAL_ENABLE registers. No prior P0/P1 test reached the
BEU blocks. Strict reads (CAUSE / ENABLE / PLIC_ENABLE per core) prove
decode; every read must return an OKAY AXI response.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

BEU_CORE_BASE = 0xC801_0000
BEU_CORE_STRIDE = 0x1000
BEU_CORES = 4

# Representative BEU register offsets (subset of the 6-register block).
BEU_CAUSE_OFFSET = 0x00
BEU_ENABLE_OFFSET = 0x10
BEU_PLIC_ENABLE_OFFSET = 0x18

# REGRESSION-LOCK values (NOT RDL-traceable). These are served by the Ascalon
# cluster black-box, not the PeakRDL bus_error_unit regblock: the RDL reset is
# CAUSE=0x0 / ENABLE=0xE6 / PLIC_ENABLE=0x0, which matches NONE of the observed
# values, and cores 2/3 read all-zero (vs RDL 0xE6) -- proof these reads come
# from the cluster model, not a live register block. Asserting the observed
# values therefore proves per-core decode/route + reachability and locks the
# current cluster-model behaviour against regression; it does NOT verify a
# spec-defined reset (golden == observed). Promote to G3 once the cluster RTL /
# RDL is integrated.
#                (CAUSE,        ENABLE,       PLIC_ENABLE)
BEU_EXPECTED = {
    0: (0x4000_0000, 0x0100_0000, 0x1F00_0000),
    1: (0x4000_0000, 0x0100_0000, 0x1F00_0000),
    2: (0x0,         0x0,         0x0),
    3: (0x0,         0x0,         0x0),
}


class smc_cluster_beu_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for core in range(BEU_CORES):
            base = BEU_CORE_BASE + core * BEU_CORE_STRIDE
            cause, enable, plic_en = BEU_EXPECTED[core]
            await self.csr_read(f"CORE{core}_BEU_CAUSE", base + BEU_CAUSE_OFFSET,
                                expected=cause)
            await self.csr_read(f"CORE{core}_BEU_ENABLE", base + BEU_ENABLE_OFFSET,
                                expected=enable)
            await self.csr_read(
                f"CORE{core}_BEU_PLIC_ENABLE", base + BEU_PLIC_ENABLE_OFFSET,
                expected=plic_en,
            )
        assert self.accesses == BEU_CORES * 3, "cluster BEU sweep count mismatch"
