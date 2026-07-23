# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: SMC_EFUSE_MAP direct read (TC_SMC_P1CG_04).

Existing tests only touch `CHIP_CONFIG_*` (mirrored eFuse fields).
This test reads the structured SMC_EFUSE_MAP window at 0xC000_B000.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Structured map (smc_top_reg.svh), not a flat word array:
#   LOCKS @ 0xB000 (64b), CHIPLET_ID @ 0xB008, PACKAGE_ID @ 0xB028,
#   BIRA @ 0xB048, ...
# LOCKS lo/hi match words 0/1 of assets/smc_efuse_default.hex (smoke default).
# CHIPLET_ID / PACKAGE_ID are read-locked → OKAY + 0xBADCAB1E (covered by
# smc_efuse_jtag_lc_negative_test); probe unlocked fields here.
EFUSE_MAP_READS = [
    ("EFUSE_MAP_LOCKS_LO", 0xC000_B000, 0xA5A5_5A5A),
    ("EFUSE_MAP_LOCKS_HI", 0xC000_B004, 0xDEAD_BEEF),
    ("EFUSE_MAP_BIRA", 0xC000_B048, None),
    ("EFUSE_MAP_RESERVED_0", 0xC000_BAFC, None),
]


class smc_efuse_map_read_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # Before fuse-sense completes the map window is error-slaved
        # (SLVERR/0xBADCAB1E). Wait for sense so VCS/Verilator hit the real path.
        await self.wait_fuse_sense_done()

        for name, addr, expected in EFUSE_MAP_READS:
            await self.csr_read(name, addr, expected=expected)
