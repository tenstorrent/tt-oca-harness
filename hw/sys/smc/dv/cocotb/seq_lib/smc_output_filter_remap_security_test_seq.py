# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Output filter/remap security representative CSR precheck."""

from __future__ import annotations

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

REMAP_FILTER_READS = [
    ("ALIAS0_START", smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0), None),
    ("ALIAS0_END", smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR", 0), None),
    ("ALIAS0_ATTRS", smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR", 0), None),
    ("OUTBOUND0_FILTER_CONFIG", smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0), None),
    ("OUTBOUND0_START", smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0), None),
    ("OUTBOUND0_END", smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0), None),
    ("OUTBOUND1_FILTER_CONFIG", 0xC001_6020, None),
]

SAFE_REMAP_FILTER_WRITES = [
    ("ALIAS0_START", smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0), 0x0000_0000),
    ("ALIAS0_END", smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR", 0), 0x0000_0FFF),
    ("OUTBOUND0_START", smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0), 0x0000_0000),
    ("OUTBOUND0_END", smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0), 0x0000_0FFF),
]


class smc_output_filter_remap_security_test_seq(SmcCsrSeq):
    """Prove remap/filter programming windows decode before responder checks."""

    def __init__(self, name: str = "smc_output_filter_remap_security_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(REMAP_FILTER_READS)

        original = []
        for name, addr, pattern in SAFE_REMAP_FILTER_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            original.append((name, addr, old_value))
            await self.csr_write(name, addr, pattern)
            await self.csr_read(f"{name}_PROBE", addr)

        for name, addr, value in reversed(original):
            await self.csr_write(f"{name}_RESTORE", addr, value)
            await self.csr_read(f"{name}_RESTORE_PROBE", addr)

        expected_accesses = len(REMAP_FILTER_READS) + (len(SAFE_REMAP_FILTER_WRITES) * 5)
        assert self.accesses == expected_accesses, "remap/filter depth mismatch"
