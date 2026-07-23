# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_cpu_firmware_boot_test (U3)."""

from __future__ import annotations

from .smc_cpu_vip_utils import (
    check_cpu_bfm_observability,
    check_cpu_firmware_boot_contract,
)
from .smc_csr_seq_utils import SmcCsrSeq


class smc_cpu_firmware_boot_test_seq(SmcCsrSeq):
    """Release SMC CPU with preloaded image and wait for PASS magic."""

    def __init__(self, name: str = "smc_cpu_firmware_boot_test_seq") -> None:
        super().__init__(name)
        self.boot: dict = {}

    async def body(self) -> None:
        await check_cpu_bfm_observability()
        self.boot = await check_cpu_firmware_boot_contract(
            self, require_image=True
        )
