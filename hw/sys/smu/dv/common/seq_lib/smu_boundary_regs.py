# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register-map and JTAG-chain constants for the wrapper boundary leaves.

Kept out of ``smu_addr_map`` and ``smu_jtag_helpers`` so the boundary leaves
own their own lookups: the generated headers they need are per-IP, and the
STAP chain order below differs from the SEP=0 one those modules carry.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_jtag_helpers import PTAP_3DCR_WIDTH, STAP_3DCR_WIDTH, stap_3dcr_payload

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SMC_ADDR_H = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "smc_addr.h"
_SMC_BASE_CONFIG_H = (
    _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h"
)
_DFX_CTRL_STATUS_H = (
    _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "dfx_ctrl_status.h"
)
_TELEMETRY_RECEIVER_H = (
    _REPO_ROOT / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)
_CROSS_TRIGGER_C = (
    _REPO_ROOT / "hw" / "ip" / "cross_trigger" / "cross_trigger_port" / "regs" / "gen" / "c",
    _REPO_ROOT / "hw" / "ip" / "cross_trigger" / "cross_trigger_matrix" / "regs" / "gen" / "c",
)

# Two-index: #define NAME(i, j) (0xBASE + (i * 0xS1) + (j * 0xS2))
_INDEXED2_RE = re.compile(
    r"^\s*#define\s+(SMC_TOP_\w+_BASE_ADDR)\(\w+,\s*\w+\)\s+"
    r"\(0x([0-9A-Fa-f]+)\s+\+\s+\(\w+\s+\*\s+0x([0-9A-Fa-f]+)\)"
    r"\s+\+\s+\(\w+\s+\*\s+0x([0-9A-Fa-f]+)\)\s*\)\s*$"
)


def smc_base_config_u32(symbol: str) -> int:
    """Return an ``SMC_BASE_CONFIG__*`` integer ``#define``."""
    return c_header_u32(_SMC_BASE_CONFIG_H, symbol)


def dfx_ctrl_status_u32(symbol: str) -> int:
    """Return a ``DFX_CTRL_STATUS__*`` integer ``#define``."""
    return c_header_u32(_DFX_CTRL_STATUS_H, symbol)


def telemetry_receiver_u32(symbol: str) -> int:
    """Return a ``TELEMETRY_RECEIVER__*`` integer ``#define``."""
    return c_header_u32(_TELEMETRY_RECEIVER_H, symbol)


def cross_trigger_u32(symbol: str) -> int:
    """Return a cross-trigger port or matrix ``#define`` from its headers."""
    paths = [
        _CROSS_TRIGGER_C[0] / "cross_trigger_port.h",
        _CROSS_TRIGGER_C[0] / "cross_trigger_port_addr.h",
        _CROSS_TRIGGER_C[1] / "cross_trigger_matrix.h",
        _CROSS_TRIGGER_C[1] / "cross_trigger_matrix_addr.h",
    ]
    for path in paths:
        try:
            return c_header_u32(path, symbol)
        except KeyError:
            continue
    raise KeyError(f"{symbol} not in any of {[str(p) for p in paths]}")


@lru_cache(maxsize=1)
def _smc_indexed2_table() -> dict[str, tuple[int, int, int]]:
    text = _SMC_ADDR_H.read_text(encoding="utf-8")
    out: dict[str, tuple[int, int, int]] = {}
    for line in text.splitlines():
        m = _INDEXED2_RE.match(line)
        if m:
            out[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16))
    if not out:
        raise RuntimeError(f"no two-index SMC_TOP_* macros parsed from {_SMC_ADDR_H}")
    return out


def smc_indexed2_addr(symbol: str, outer: int = 0, inner: int = 0) -> int:
    """Return ``BASE + outer*S1 + inner*S2`` for a two-index ``SMC_TOP_*`` macro."""
    table = _smc_indexed2_table()
    try:
        base, s_outer, s_inner = table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not a two-index macro in {_SMC_ADDR_H}") from exc
    return base + int(outer) * s_outer + int(inner) * s_inner


# jtag_intf_unit.sv daisy-chains the secondary TAPs in instantiation order, and
# smu_pkg.sv turns on STAP_IO, SMC_DBG, SEP_DBG (with SEP) and one extra STAP.
# smu_jtag_helpers.SMU_STAP_ORDER is the SEP=0 chain; this is the SEP=1 one.
SEP_RTL_STAP_ORDER = ("io", "smc", "sep", "extra0")


def stap_sib_pattern(name: str, enabled: int = 1, order: tuple[str, ...] = ()) -> int:
    """SIB open/close bit for ``name`` in the given chain order."""
    chain = order or SEP_RTL_STAP_ORDER
    return (enabled & 0x1) << (len(chain) - 1 - chain.index(name))


def stap_3dcr_scan_word(
    name: str,
    *,
    config_hold: int,
    stap_sel: int,
    tms_hold: int,
    close_sib: int = 0,
    order: tuple[str, ...] = (),
) -> tuple[int, int]:
    """SIB bits then the 3-bit STAP 3DCR, for the given chain order."""
    chain = order or SEP_RTL_STAP_ORDER
    payload = stap_3dcr_payload(config_hold=config_hold, stap_sel=stap_sel, tms_hold=tms_hold)
    value = (close_sib & 0x1) << (len(chain) - 1 - chain.index(name))
    value |= payload << len(chain)
    return value, len(chain) + STAP_3DCR_WIDTH


def ptap_prefixed(
    stap_word: int, stap_width: int, *, config_hold: int = 1, select: int = 1
) -> tuple[int, int]:
    """Prefix the PTAP 3DCR bits so a TAP_3DCR DR shift keeps stap_select."""
    ptap = (config_hold & 0x1) | ((select & 0x1) << 1)
    return (ptap << stap_width) | (stap_word & ((1 << stap_width) - 1)), (
        PTAP_3DCR_WIDTH + stap_width
    )
