# SPDX-License-Identifier: Apache-2.0
"""eFuse/OTP and clock-control representative CSR precheck."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
CHIP_CONFIG_READS = [
    ("CHIP_CONFIG_VERSION_LO", 0xC000_2900, 0x0001_00A0),
    ("CHIP_CONFIG_VERSION_HI", 0xC000_2904, 0),
    ("CHIP_CONFIG_CHIP_ID", 0xC000_2908, None),
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
