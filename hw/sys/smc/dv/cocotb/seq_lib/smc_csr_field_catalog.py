# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Field-aware CSR catalog for OSS-safe SMC register tests."""

from __future__ import annotations

from .smc_addr_map import smc_addr
from dataclasses import dataclass
from enum import Enum


class SmcCsrAccessKind(Enum):
    RW_RESTORE = "rw_restore"
    RO_STATIC = "ro_static"
    RO_STATUS = "ro_status"


@dataclass(frozen=True)
class SmcCsrField:
    name: str
    addr: int
    kind: SmcCsrAccessKind
    expected: int | None = None


CSR_FIELD_CATALOG = {
    "SCRATCH_COLD_0": SmcCsrField("SCRATCH_COLD_0", smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR"),
                                  SmcCsrAccessKind.RW_RESTORE, 0),
    "SCRATCH_COLD_1": SmcCsrField("SCRATCH_COLD_1", smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + 0x4,
                                  SmcCsrAccessKind.RW_RESTORE, 0),
    "SCRATCH_COLD_7": SmcCsrField("SCRATCH_COLD_7", smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + 0x1C,
                                  SmcCsrAccessKind.RW_RESTORE, 0),
    "SCRATCH_COLD_WARM_0": SmcCsrField("SCRATCH_COLD_WARM_0", smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR"),
                                       SmcCsrAccessKind.RW_RESTORE, 0),
    "SCRATCH_COLD_WARM_7": SmcCsrField("SCRATCH_COLD_WARM_7", 0xC000_289C,
                                       SmcCsrAccessKind.RW_RESTORE, 0),
    "CHIP_CONFIG_VERSION_LO": SmcCsrField("CHIP_CONFIG_VERSION_LO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR"),
                                          SmcCsrAccessKind.RO_STATIC, 0x0001_00A0),
    "CHIP_CONFIG_VERSION_HI": SmcCsrField("CHIP_CONFIG_VERSION_HI", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x4,
                                          SmcCsrAccessKind.RO_STATIC, 0),
    "CHIP_CONFIG_CHIP_ID": SmcCsrField("CHIP_CONFIG_CHIP_ID", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR") + 0x8,
                                       SmcCsrAccessKind.RO_STATIC, None),
    "CHIP_CONFIG_RAS_BANK_INFO": SmcCsrField("CHIP_CONFIG_RAS_BANK_INFO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_RAS_BANK_INFO_BASE_ADDR"),
                                            SmcCsrAccessKind.RO_STATIC, None),
    "NDM_RESET_STATUS": SmcCsrField("NDM_RESET_STATUS", 0xC000_2A00,
                                    SmcCsrAccessKind.RO_STATUS, None),
}


def catalog_entry(name: str, addr: int, writable: bool) -> SmcCsrField:
    """Return and validate a CSR catalog entry used by a test sequence."""
    entry = CSR_FIELD_CATALOG[name]
    assert entry.addr == addr, f"{name} catalog addr mismatch: 0x{entry.addr:x} != 0x{addr:x}"
    if writable:
        assert entry.kind is SmcCsrAccessKind.RW_RESTORE, f"{name} is not cataloged as RW"
    else:
        assert entry.kind is not SmcCsrAccessKind.RW_RESTORE, f"{name} is unexpectedly RW"
    return entry
