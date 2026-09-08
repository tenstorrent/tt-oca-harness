# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap: SMC_EFUSE_MAP direct read (TC_SMC_P1CG_04).

Existing tests only touch `CHIP_CONFIG_*` (mirrored eFuse fields).
This test reads the structured SMC_EFUSE_MAP window (PeakRDL map).
"""

from __future__ import annotations

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Structured map (PeakRDL smc_addr.h), not a flat word array.
# LOCKS lo/hi match words 0/1 of assets/smc_efuse_default.hex (smoke default).
# That golden read-locks JTAG_PUBLIC_IDENTITY and SPARE[0] (they return OKAY + 0xBADCAB1E,
# a path covered by smc_efuse_jtag_lc_negative_test), so the targets below are
# the read-unlocked ones: SMC_CONFIG and SPARE[2] are write-locked only.
EFUSE_MAP_READS = [
    ("EFUSE_MAP_LOCKS_LO", smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR"),
     0xA5A5_5A5A),
    ("EFUSE_MAP_LOCKS_HI", smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR") + 4,
     0xDEAD_BEEF),
    ("EFUSE_MAP_SMC_CONFIG", smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR"),
     None),
    ("EFUSE_MAP_SPARE_2", smc_indexed_addr(
        "SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 2), None),
]


class smc_efuse_map_read_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # Before fuse-sense completes the map window is error-slaved
        # (SLVERR/0xBADCAB1E). Wait for sense so VCS/Verilator hit the real path.
        await self.wait_fuse_sense_done()

        for name, addr, expected in EFUSE_MAP_READS:
            await self.csr_read(name, addr, expected=expected)
