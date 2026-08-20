# SPDX-License-Identifier: Apache-2.0
"""Canonical DTP debug-disable metadata.

The DUT takes ``sep_lifecycle_ctrl_pkg::dbg_disable_t``: eleven pre-resolved
active-high disables, one per gated interface (1 = interface disabled).
``tb_top.sv`` exposes one scalar input per field, named ``dbg_disable_<field>``.
"""

from __future__ import annotations

from collections.abc import Mapping

# Declaration order of sep_lifecycle_ctrl_pkg::dbg_disable_t (MSB first).
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

# The five legacy lifecycle enables of the pre-resolved derivation (now in
# sep_lifecycle_ctrl at the SEP level).
LIFECYCLE_ENABLE_NAMES: tuple[str, ...] = (
    "sip_debug",
    "soc_debug",
    "ap_debug",
    "sep_debug",
    "fuse_test",
)

# Enables that must all be high for each interface to be enabled. This is the
# derivation the DTP RTL performed before it took dbg_disable_i directly; the
# interim five-enable sequence API uses it until tests drive disables directly.
REQUIRED_ENABLES: dict[str, tuple[str, ...]] = {
    "stap_io": ("sip_debug",),
    "stap_smc": ("soc_debug", "ap_debug"),
    "stap_sep": ("sep_debug", "soc_debug", "ap_debug"),
    "stap_extra": ("ap_debug",),
    "stap_host": ("ap_debug",),
    "dft_secure": ("fuse_test", "sep_debug", "soc_debug", "ap_debug"),
    "dft_nonsecure": ("soc_debug", "ap_debug"),
    "dfd": ("ap_debug",),
    "smc_jtag2axi": ("soc_debug", "ap_debug"),
    "smc_otp_jtag2axi": ("fuse_test", "soc_debug", "ap_debug"),
    "sep_otp_jtag2axi": ("fuse_test", "sep_debug", "soc_debug", "ap_debug"),
}

# Enable state tracked across the interim five-enable API calls within one
# test process. The bring-up startup vector enables everything, so partial
# set_lifecycle() updates merge into an all-enabled baseline.
_current_enables: dict[str, int] = {name: 1 for name in LIFECYCLE_ENABLE_NAMES}


def disables_from_enables(enables: Mapping[str, int]) -> dict[str, int]:
    """Derive the eleven active-high disables from the five legacy enables."""
    unknown = set(enables) - set(LIFECYCLE_ENABLE_NAMES)
    if unknown:
        raise ValueError(f"unknown lifecycle feature(s): {sorted(unknown)}")
    return {
        field: int(not all(int(enables.get(name, 0)) & 1 for name in required))
        for field, required in REQUIRED_ENABLES.items()
    }


def update_enables(**bits: int) -> dict[str, int]:
    """Merge partial enable updates into the tracked state; return disables."""
    unknown = set(bits) - set(LIFECYCLE_ENABLE_NAMES)
    if unknown:
        raise ValueError(f"unknown lifecycle feature(s): {sorted(unknown)}")
    for name, value in bits.items():
        _current_enables[name] = int(value) & 1
    return disables_from_enables(_current_enables)


def format_dbg_disable(values: Mapping[str, int]) -> str:
    """Deterministic 'field=value' log string in struct declaration order."""
    return " ".join(f"{name}={int(values[name]) & 1}" for name in DBG_DISABLE_FIELDS)
