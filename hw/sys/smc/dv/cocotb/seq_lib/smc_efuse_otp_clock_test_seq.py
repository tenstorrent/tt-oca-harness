# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse/OTP and clock-control representative CSR precheck."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
CHIP_CONFIG_READS = [
    ("CHIP_CONFIG_VERSION_LO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR"), 0x0001_00A0),
    ("CHIP_CONFIG_VERSION_HI", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x4, 0),
    ("CHIP_CONFIG_CHIP_ID", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x8, None),
]


class smc_efuse_otp_clock_test_seq(SmcCsrSeq):
    """Use OSS-safe chip-config fields as eFuse/OTP observable proxy."""

    def __init__(self, name: str = "smc_efuse_otp_clock_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        clock_gate = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_read_many(CHIP_CONFIG_READS)
        await self.csr_read("CLOCK_GATE_CONTROL_RECHECK", CLOCK_GATE_CONTROL,
                            expected=clock_gate)
        assert self.accesses == len(CHIP_CONFIG_READS) + 2, "eFuse proxy read mismatch"
