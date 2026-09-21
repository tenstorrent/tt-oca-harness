# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Compact register-boundary depth sweep over real SEP_IN AXI."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_field_catalog import catalog_entry, misc_wrap_reset
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_7 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + 0x1C
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SCRATCH_COLD_WARM_7 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR") + 0x1C

BOUNDARY_READS = [
    ("SCRATCH_COLD_0", SCRATCH_COLD_0, 0),
    ("SCRATCH_COLD_7", SCRATCH_COLD_7, 0),
    ("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, 0),
    ("SCRATCH_COLD_WARM_7", SCRATCH_COLD_WARM_7, 0),
    (
        "CHIP_CONFIG_VERSION_LO",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR"),
        misc_wrap_reset("CHIP_CONFIG__VERSION_LO__VERSION_LO_reset"),
    ),
    ("CHIP_CONFIG_VERSION_HI", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x4, 0),
]

BOUNDARY_WRITES = [
    ("SCRATCH_COLD_7", SCRATCH_COLD_7, 0x1357_2468),
    ("SCRATCH_COLD_WARM_7", SCRATCH_COLD_WARM_7, 0x2468_1357),
]


class smc_register_boundary_depth_test_seq(SmcCsrSeq):
    """Exercise safe first/last registers from representative CSR windows."""

    def __init__(self, name: str = "smc_register_boundary_depth_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for name, addr, _expected in BOUNDARY_READS:
            catalog_entry(name, addr, writable=name.startswith("SCRATCH_"))
        for name, addr, _pattern in BOUNDARY_WRITES:
            catalog_entry(name, addr, writable=True)

        await self.csr_read_many(BOUNDARY_READS)

        original = []
        for name, addr, pattern in BOUNDARY_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            original.append((name, addr, old_value))
            await self.csr_write_readback(name, addr, pattern)

        for name, addr, value in reversed(original):
            await self.csr_restore(name, addr, value)

        expected_accesses = len(BOUNDARY_READS) + (len(BOUNDARY_WRITES) * 5)
        assert self.accesses == expected_accesses, "register boundary sweep mismatch"
