# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical DTP debug-disable metadata.

The DUT's ``dbg_disable_i`` port carries eleven pre-resolved active-high
disables, one per gated path (1 = path disabled); the Debug Disable table in
``hw/sys/dtp/doc/jtag.adoc`` names them. ``dtp_tb_if`` exposes one
``dbg_disable_<field>`` member per name and binds each to its struct field,
so this module holds the name set and the per-path name maps only.
Deriving these disables from lifecycle policy is SEP-level behavior; DTP DV
drives and checks each field directly.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = [
    "DBG_DISABLE_FIELDS",
    "IJTAG_SIB_DISABLE",
    "JTAG2AXI_DISABLE",
    "STAP_DISABLE",
    "format_dbg_disable",
    "full_dbg_disable",
    "validate_dbg_disable",
]

# The eleven disable fields in the row order of the Debug Disable table in
# hw/sys/dtp/doc/jtag.adoc; the order serves logging only.
DBG_DISABLE_FIELDS: tuple[str, ...] = (
    "stap_io",
    "stap_smc",
    "stap_sep",
    "stap_extra",
    "stap_host",
    "dft_secure",
    "dft_nonsecure",
    "dfd",
    "smc_jtag2axi",
    "smc_otp_jtag2axi",
    "sep_otp_jtag2axi",
)

# iJTAG SIB name (dtp_scan_ref_model.IJTAG_SIB_ORDER) -> disable field.
IJTAG_SIB_DISABLE: dict[str, str] = {
    "dft_secure": "dft_secure",
    "dft": "dft_nonsecure",
    "dfd": "dfd",
}

# STAP name (dtp_scan_ref_model.STAP_ORDER plus the extended host scan
# interface) -> disable field.
STAP_DISABLE: dict[str, str] = {
    "io": "stap_io",
    "smc": "stap_smc",
    "sep": "stap_sep",
    "extra0": "stap_extra",
    "stap_host": "stap_host",
}

# JTAG2AXI target name (dtp_types.JTAG2AXI_TARGETS) -> disable field.
JTAG2AXI_DISABLE: dict[str, str] = {
    "smc_axi": "smc_jtag2axi",
    "smc_otp": "smc_otp_jtag2axi",
    "sep_otp": "sep_otp_jtag2axi",
}


def validate_dbg_disable(values: Mapping[str, int]) -> dict[str, int]:
    """Normalize a named (possibly partial) disable mask; reject unknown names."""
    unknown = set(values) - set(DBG_DISABLE_FIELDS)
    if unknown:
        raise ValueError(f"unknown dbg_disable field(s): {sorted(unknown)}")
    return {name: int(values[name]) & 1 for name in values}


def full_dbg_disable(values: Mapping[str, int] | None = None) -> dict[str, int]:
    """Return a complete eleven-field mask; unnamed fields default to enabled (0)."""
    named = validate_dbg_disable(values or {})
    return {name: named.get(name, 0) for name in DBG_DISABLE_FIELDS}


def format_dbg_disable(values: Mapping[str, int]) -> str:
    """Deterministic 'field=value' log string in table order."""
    return " ".join(
        f"{name}={int(values[name]) & 1}" for name in DBG_DISABLE_FIELDS if name in values
    )
