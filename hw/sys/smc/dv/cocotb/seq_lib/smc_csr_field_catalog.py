# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Field-aware CSR catalog for OSS-safe SMC register tests.

Both halves of every default compare are symbol-sourced from the generated
PeakRDL output ([ADDRESS-FROM-AUTHORITATIVE-MAP]): the address from
``hw/sys/smc/regs/gen/c/smc_addr.h``, and the expected value from the matching
``*_reset`` constant in ``hw/sys/smc/regs/gen/c/blocks/misc_wrap.h``. An entry
with ``expected=None`` is decode-only evidence and the comment beside it says
why no generated whole-word default exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ``_field_mask`` is the generic "read one plain ``#define`` out of a generated
# PeakRDL C header" accessor; ``smc_addr_map`` exposes it per block
# (``cpu_ctrl_u32``, ``reset_unit_u32``, ...) but has no ``misc_wrap`` wrapper,
# so the module-private helper is reused rather than a second #define parser
# ([REUSE-AND-LAYERING]).
from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr

# Authoritative addressing: every catalog address below is evaluated from a
# generated PeakRDL symbol in ``hw/sys/smc/regs/gen/c/smc_addr.h`` (indexed
# ``SCRATCH_BASE_ADDR(idx)`` macros for the scratch arrays, per-register
# ``*_BASE_ADDR`` for the chip_config / ndm_reset words). No hand-maintained
# strides or absolute literals: the catalog and the sequences that cross-check
# against it share one source, so a regenerated RDL moves both together.
_SCRATCH_COLD = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
_SCRATCH_COLD_WARM = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR"

# Authoritative *expected values*: the right-hand side of every default compare
# below is imported by symbol from the generated block header, exactly like the
# addresses above ([ADDRESS-FROM-AUTHORITATIVE-MAP]). No hand-typed reset
# literals: a regenerated RDL moves address and expected value together.
_MISC_WRAP_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "misc_wrap.h"


def misc_wrap_reset(symbol: str) -> int:
    """Reset (default) constant of a ``misc_wrap`` field from the generated header."""
    return _field_mask(_MISC_WRAP_H, symbol)


_SCRATCH_DATA_RESET = misc_wrap_reset("SCRATCH__SCRATCH__DATA_reset")
_VERSION_LO_RESET = misc_wrap_reset("CHIP_CONFIG__VERSION_LO__VERSION_LO_reset")
_VERSION_HI_RESET = misc_wrap_reset("CHIP_CONFIG__VERSION_HI__VERSION_HI_reset")
# chip_config.CHIP_ID is `hw = w`: smc_misc_wrap drives it from its ``CHIP_ID``
# module parameter (`smc_misc_wrap.sv:9,209`), so the read-back is a per-variant
# integration constant rather than a register default that the RDL reset value
# alone guarantees. The OSS TB leaves the parameter at its default, and the
# generated map's reset constant is that same default -- so the compare below is
# exact, symbol-sourced, and fails loudly (rather than silently skipping) if a
# variant ever drives a different CHIP_ID than the map declares.
_CHIP_ID_RESET = misc_wrap_reset("CHIP_CONFIG__CHIP_ID__CHIP_ID_reset")


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
    "SCRATCH_COLD_0": SmcCsrField(
        "SCRATCH_COLD_0",
        smc_indexed_addr(_SCRATCH_COLD, 0),
        SmcCsrAccessKind.RW_RESTORE,
        _SCRATCH_DATA_RESET,
    ),
    "SCRATCH_COLD_1": SmcCsrField(
        "SCRATCH_COLD_1",
        smc_indexed_addr(_SCRATCH_COLD, 1),
        SmcCsrAccessKind.RW_RESTORE,
        _SCRATCH_DATA_RESET,
    ),
    "SCRATCH_COLD_7": SmcCsrField(
        "SCRATCH_COLD_7",
        smc_indexed_addr(_SCRATCH_COLD, 7),
        SmcCsrAccessKind.RW_RESTORE,
        _SCRATCH_DATA_RESET,
    ),
    "SCRATCH_COLD_WARM_0": SmcCsrField(
        "SCRATCH_COLD_WARM_0",
        smc_indexed_addr(_SCRATCH_COLD_WARM, 0),
        SmcCsrAccessKind.RW_RESTORE,
        _SCRATCH_DATA_RESET,
    ),
    "SCRATCH_COLD_WARM_1": SmcCsrField(
        "SCRATCH_COLD_WARM_1",
        smc_indexed_addr(_SCRATCH_COLD_WARM, 1),
        SmcCsrAccessKind.RW_RESTORE,
        _SCRATCH_DATA_RESET,
    ),
    "SCRATCH_COLD_WARM_7": SmcCsrField(
        "SCRATCH_COLD_WARM_7",
        smc_indexed_addr(_SCRATCH_COLD_WARM, 7),
        SmcCsrAccessKind.RW_RESTORE,
        _SCRATCH_DATA_RESET,
    ),
    "CHIP_CONFIG_VERSION_LO": SmcCsrField(
        "CHIP_CONFIG_VERSION_LO",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR"),
        SmcCsrAccessKind.RO_STATIC,
        _VERSION_LO_RESET,
    ),
    "CHIP_CONFIG_VERSION_HI": SmcCsrField(
        "CHIP_CONFIG_VERSION_HI",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR"),
        SmcCsrAccessKind.RO_STATIC,
        _VERSION_HI_RESET,
    ),
    "CHIP_CONFIG_CHIP_ID": SmcCsrField(
        "CHIP_CONFIG_CHIP_ID",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR"),
        SmcCsrAccessKind.RO_STATIC,
        _CHIP_ID_RESET,
    ),
    # 0xC000_2A00 is NDM_RESET.NDMRESET_REQUEST, not a "status" register: the
    # entry carries the name of the symbol that addresses it so a logged
    # register identity cannot drift from the address actually accessed.
    "NDM_RESET_NDMRESET_REQUEST": SmcCsrField(
        "NDM_RESET_NDMRESET_REQUEST",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR"),
        SmcCsrAccessKind.RO_STATUS,
        None,
    ),
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
