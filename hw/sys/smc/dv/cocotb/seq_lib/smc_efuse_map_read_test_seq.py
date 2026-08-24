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
# CHIPLET_ID / PACKAGE_ID are read-locked → OKAY + 0xBADCAB1E (covered by
# smc_efuse_jtag_lc_negative_test); probe unlocked fields here.
EFUSE_MAP_READS = [
    ("EFUSE_MAP_LOCKS_LO", smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR"),
     0xA5A5_5A5A),
    ("EFUSE_MAP_LOCKS_HI", smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR") + 4,
     0xDEAD_BEEF),
    ("EFUSE_MAP_BIRA", smc_addr("SMC_TOP_SMC_EFUSE_MAP_BIRA_BASE_ADDR"), None),
    ("EFUSE_MAP_RESERVED_0", smc_indexed_addr(
        "SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR", 0), None),
]


class smc_efuse_map_read_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # Before fuse-sense completes the map window is error-slaved
        # (SLVERR/0xBADCAB1E). Wait for sense so VCS/Verilator hit the real path.
        await self.wait_fuse_sense_done()

        for name, addr, expected in EFUSE_MAP_READS:
            await self.csr_read(name, addr, expected=expected)
