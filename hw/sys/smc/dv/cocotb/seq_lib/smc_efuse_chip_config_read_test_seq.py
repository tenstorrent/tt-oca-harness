# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse-derived chip-config read depth test."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_field_catalog import misc_wrap_reset
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import prove_efuse_bank_axil_activity

# VERSION_LO=CHIP_CONFIG_VERSION_LO reset from the generated header / VERSION_HI=0 / CHIP_ID=0 / all trace to
# chip_config.rdl reset constants (identical on Verilator and VCS) -> G3
# spec-anchored decode + reset-value check. LC_STATE is left decode-only
# (expected=None): it is simulator-divergent in the OSS bench (Verilator's
# efuse model presents 0xF0 while VCS reads 0x0), so no single value assertion
# holds on both.
#
# Each register is addressed by its own generated symbol: several expectations
# are 0, which is also what unmapped space returns, so a wrong offset would pass
# rather than fail here.
CHIP_CONFIG_EFUSE_READS = [
    (
        "VERSION_LO",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR"),
        misc_wrap_reset("CHIP_CONFIG__VERSION_LO__VERSION_LO_reset"),
    ),
    ("VERSION_HI", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR"), 0),
    ("CHIP_ID", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR"), 0x0),
    ("LC_STATE", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR"), None),
]


class smc_efuse_chip_config_read_test_seq(SmcCsrSeq):
    """Use chip-config fields as the OSS-safe eFuse observable surface."""

    def __init__(self, name: str = "smc_efuse_chip_config_read_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # Positive control first, so the eFuse-bank idle leg the callers run
        # afterwards (check_efuse_otp_observability) is backed by an observed
        # 0 -> 1 -> 0 on tb_axil_efuse_bank_active in this same run. Without it
        # that helper only logs a warning and the idle observation is vacuous.
        await prove_efuse_bank_axil_activity(self)
        await self.csr_read_many(CHIP_CONFIG_EFUSE_READS)
        expected_accesses = len(CHIP_CONFIG_EFUSE_READS) + 1  # + the positive control read
        assert self.accesses == expected_accesses, (
            f"eFuse chip-config mismatch: issued {self.accesses}, expected {expected_accesses}"
        )
