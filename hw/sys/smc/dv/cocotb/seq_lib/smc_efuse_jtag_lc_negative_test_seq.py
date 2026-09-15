# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helpers for smc_efuse_jtag_lc_negative_test (PROD deny / identity allow).

The lifecycle-gated JTAG eFuse policy is exercised end-to-end in the test via
``tb_lc_state`` + ``ej_axi`` (same ports as the access-matrix test). This
module only holds PeakRDL addresses and the CHIP_CONFIG LC_STATE CSR probe
used as a secondary observability check over SEP_IN.
"""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# PeakRDL smc_addr.h — SMC_EFUSE_MAP identity / lock windows.
CHIP_CONFIG_LC_STATE = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR")
SMC_EFUSE_MAP_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY = smc_addr(
    "SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR"
)


class smc_efuse_jtag_lc_negative_test_seq(SmcCsrSeq):
    """Strict SEP_IN read of CHIP_CONFIG_LC_STATE (exact expected required)."""

    def __init__(self, name: str = "smc_efuse_jtag_lc_negative_test_seq") -> None:
        super().__init__(name)
        self.lc_state = 0

    async def body(self) -> None:
        raise NotImplementedError(
            "Use read_lc_state_exact(); JTAG deny/allow is scored in the test"
        )

    async def read_lc_state_exact(self, expected: int) -> int:
        """Fail if CHIP_CONFIG_LC_STATE is unreachable or value mismatches."""
        self.lc_state = await self.csr_read(
            "CHIP_CONFIG_LC_STATE",
            CHIP_CONFIG_LC_STATE,
            expected=expected,
        )
        assert self.timeouts == 0, "CHIP_CONFIG_LC_STATE timed out"
        return self.lc_state
