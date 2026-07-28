# SPDX-License-Identifier: Apache-2.0
"""JTAG/DFT blocked-window timeout proxy test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

DFT_CTRL_STATUS_SMU = 0xC000_F800
CHIP_CONFIG_VERSION_LO = 0xC000_2900


class smc_jtag_dft_timeout_proxy_test_seq(SmcCsrSeq):
    """Document the current public DFT window behavior before JTAG VIP exists."""

    def __init__(self, name: str = "smc_jtag_dft_timeout_proxy_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read("CHIP_CONFIG_VERSION_LO", CHIP_CONFIG_VERSION_LO,
                            expected=0x0001_00A0)
        await self.csr_short_timeout("DFT_CTRL_STATUS_SMU", DFT_CTRL_STATUS_SMU)
        await self.csr_read("CHIP_CONFIG_VERSION_LO_RECOVERY", CHIP_CONFIG_VERSION_LO,
                            expected=0x0001_00A0)
        assert self.accesses == 3 and self.timeouts == 1, "JTAG/DFT proxy mismatch"
