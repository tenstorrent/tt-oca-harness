# SPDX-License-Identifier: Apache-2.0
"""eFuse-derived chip-config read depth test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# VERSION_LO=0x000100A0 / VERSION_HI=0 / CHIP_ID=0 / RAS_BANK_INFO=0 all trace to
# chip_config.rdl reset constants (identical on Verilator and VCS) -> G3
# spec-anchored decode + reset-value check. LC_STATE (0xC000_290C) is left
# decode-only (expected=None): it is simulator-divergent in the OSS bench
# (Verilator's efuse model presents 0xF0 while VCS reads 0x0), so no single
# value assertion holds on both.
CHIP_CONFIG_EFUSE_READS = [
    ("VERSION_LO", 0xC000_2900, 0x0001_00A0),
    ("VERSION_HI", 0xC000_2904, 0),
    ("CHIP_ID", 0xC000_2908, 0x0),
    ("LC_STATE", 0xC000_290C, None),
    ("RAS_BANK_INFO", 0xC000_2910, 0x0),
]


class smc_efuse_chip_config_read_test_seq(SmcCsrSeq):
    """Use chip-config fields as the OSS-safe eFuse observable surface."""

    def __init__(self, name: str = "smc_efuse_chip_config_read_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(CHIP_CONFIG_EFUSE_READS)
        assert self.accesses == len(CHIP_CONFIG_EFUSE_READS), "eFuse chip-config mismatch"
