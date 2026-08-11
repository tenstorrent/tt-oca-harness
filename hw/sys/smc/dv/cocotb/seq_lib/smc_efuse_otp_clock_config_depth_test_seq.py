# SPDX-License-Identifier: Apache-2.0
"""eFuse/OTP observable clock-config depth test over real SEP_IN AXI."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
CLOCK_GATE_PATTERN = (1 << 8) | (1 << 11) | (1 << 12)
CLOCK_GATE_MASK = 0x0000_1FFF

EFUSE_PROXY_READS = [
    ("CHIP_CONFIG_VERSION_LO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR"), 0x0001_00A0),
    ("CHIP_CONFIG_VERSION_HI", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x4, 0),
    ("CHIP_CONFIG_CHIP_ID", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x8, None),
    ("CHIP_CONFIG_LC_STATE", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0xC, None),
    ("CHIP_CONFIG_RAS_BANK_INFO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_RAS_BANK_INFO_BASE_ADDR"), None),
]


class smc_efuse_otp_clock_config_depth_test_seq(SmcCsrSeq):
    """Use OSS-safe fuse observability plus clock-gate RW depth."""

    def __init__(self, name: str = "smc_efuse_otp_clock_config_depth_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_read_many(EFUSE_PROXY_READS)

        pattern = (original & ~CLOCK_GATE_MASK) | CLOCK_GATE_PATTERN
        await self.csr_write("CLOCK_GATE_CONTROL_PATTERN", CLOCK_GATE_CONTROL, pattern)
        got = await self.csr_read("CLOCK_GATE_CONTROL_PATTERN", CLOCK_GATE_CONTROL)
        assert (got & CLOCK_GATE_MASK) == CLOCK_GATE_PATTERN, (
            f"clock gate readback 0x{got:x} does not match mask 0x{CLOCK_GATE_MASK:x}"
        )
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=original)

        expected_accesses = len(EFUSE_PROXY_READS) + 5
        assert self.accesses == expected_accesses, "eFuse OTP config depth mismatch"
