# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Load SMC CSR addresses from the generated PeakRDL C header (authoritative map)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SMC_ADDR_H = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "smc_addr.h"
_FILTER_CTRL_H = _REPO_ROOT / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_CPU_CTRL_H = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"
_CHIP_CONFIG_H = (
    _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "chip_config.h"
)
_SYSTEM_TIMER_OCTS_H = (
    _REPO_ROOT / "hw" / "ip" / "system_timer_octs" / "regs" / "gen" / "c" / "system_timer_octs.h"
)
_WDT_H = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "wdt.h"
_RESET_UNIT_H = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "reset_unit.h"
_AXIL_MAILBOX_H = (
    _REPO_ROOT / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)
_SMC_BASE_CONFIG_H = (
    _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h"
)
_DFX_CTRL_STATUS_H = (
    _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "dfx_ctrl_status.h"
)
_TELEMETRY_RECEIVER_H = (
    _REPO_ROOT / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)

_DEFINE_RE = re.compile(r"^\s*#define\s+(SMC_TOP_\w+)\s+(0x[0-9A-Fa-f]+|\d+)\s*$")
_ANY_DEFINE_RE = re.compile(r"^\s*#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\s*$")
# Indexed: #define NAME(idx) (0xBASE + (idx * 0xSTRIDE))
_INDEXED_RE = re.compile(
    r"^\s*#define\s+(SMC_TOP_\w+_BASE_ADDR)\(\w+\)\s+"
    r"\(0x([0-9A-Fa-f]+)\s+\+\s+\(\w+\s+\*\s+0x([0-9A-Fa-f]+)\)\s*\)\s*$"
)
# Two-index: #define NAME(i, j) (0xBASE + (i * 0xS1) + (j * 0xS2))
_INDEXED2_RE = re.compile(
    r"^\s*#define\s+(SMC_TOP_\w+_BASE_ADDR)\(\w+,\s*\w+\)\s+"
    r"\(0x([0-9A-Fa-f]+)\s+\+\s+\(\w+\s+\*\s+0x([0-9A-Fa-f]+)\)"
    r"\s+\+\s+\(\w+\s+\*\s+0x([0-9A-Fa-f]+)\)\s*\)\s*$"
)
_BM_RE = re.compile(r"^\s*#define\s+(FILTER_CTRL__FILTER_CONFIG__\w+_bm)\s+(0x[0-9A-Fa-f]+)\s*$")
_BP_RE = re.compile(r"^\s*#define\s+(FILTER_CTRL__FILTER_CONFIG__\w+_bp)\s+(\d+)\s*$")
_RESET_RE = re.compile(
    r"^\s*#define\s+(FILTER_CTRL__FILTER_CONFIG__\w+_reset)\s+(0x[0-9A-Fa-f]+|\d+)\s*$"
)


@lru_cache(maxsize=1)
def _smc_addr_table() -> dict[str, int]:
    text = _SMC_ADDR_H.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = _DEFINE_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    if not out:
        raise RuntimeError(f"no SMC_TOP_* defines parsed from {_SMC_ADDR_H}")
    return out


@lru_cache(maxsize=1)
def _smc_indexed_table() -> dict[str, tuple[int, int]]:
    """Return {BASE_ADDR_macro: (base, stride)} from smc_addr.h."""
    text = _SMC_ADDR_H.read_text(encoding="utf-8")
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        m = _INDEXED_RE.match(line)
        if m:
            out[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    if not out:
        raise RuntimeError(f"no indexed SMC_TOP_* macros parsed from {_SMC_ADDR_H}")
    return out


@lru_cache(maxsize=1)
def _smc_indexed2_table() -> dict[str, tuple[int, int, int]]:
    """Return {BASE_ADDR_macro: (base, stride_outer, stride_inner)} from smc_addr.h."""
    text = _SMC_ADDR_H.read_text(encoding="utf-8")
    out: dict[str, tuple[int, int, int]] = {}
    for line in text.splitlines():
        m = _INDEXED2_RE.match(line)
        if m:
            out[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16))
    if not out:
        raise RuntimeError(f"no two-index SMC_TOP_* macros parsed from {_SMC_ADDR_H}")
    return out


@lru_cache(maxsize=1)
def _filter_ctrl_field_table() -> dict[str, dict[str, int]]:
    """Parse filter_ctrl.h into {FIELD: {bm, bp, reset}}."""
    text = _FILTER_CTRL_H.read_text(encoding="utf-8")
    out: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        for kind, rx in (
            ("bm", _BM_RE),
            ("bp", _BP_RE),
            ("reset", _RESET_RE),
        ):
            m = rx.match(line)
            if not m:
                continue
            full = m.group(1)
            # FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm → ALLOW_NS
            core = full.removeprefix("FILTER_CTRL__FILTER_CONFIG__")
            field, _, _suffix = core.rpartition("_")
            out.setdefault(field, {})[kind] = int(m.group(2), 0)
    if not out:
        raise RuntimeError(f"no FILTER_CTRL fields parsed from {_FILTER_CTRL_H}")
    return out


def filter_ctrl_bm(symbol: str) -> int:
    """Return a ``FILTER_CTRL__FILTER_CONFIG__*_bm`` mask from ``filter_ctrl.h``."""
    if not symbol.endswith("_bm"):
        raise KeyError(f"expected *_bm symbol, got {symbol}")
    field = symbol.removeprefix("FILTER_CTRL__FILTER_CONFIG__").removesuffix("_bm")
    table = _filter_ctrl_field_table()
    try:
        return table[field]["bm"]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {_FILTER_CTRL_H}") from exc


def filter_ctrl_field_encode(field: str, value: int) -> int:
    """Encode ``value`` into a FILTER_CONFIG field using header bp/bm."""
    table = _filter_ctrl_field_table()
    try:
        meta = table[field]
        bp, bm = meta["bp"], meta["bm"]
    except KeyError as exc:
        raise KeyError(f"FILTER_CONFIG.{field} not in {_FILTER_CTRL_H}") from exc
    enc = (int(value) << bp) & bm
    return enc


def filter_ctrl_field_reset_encode(field: str) -> int:
    """Encode the PeakRDL reset value for ``field`` at its bit position."""
    table = _filter_ctrl_field_table()
    try:
        meta = table[field]
    except KeyError as exc:
        raise KeyError(f"FILTER_CONFIG.{field} not in {_FILTER_CTRL_H}") from exc
    return filter_ctrl_field_encode(field, meta["reset"])


def smc_addr(symbol: str) -> int:
    """Return address for a ``SMC_TOP_*`` symbol from ``smc_addr.h``."""
    table = _smc_addr_table()
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {_SMC_ADDR_H}") from exc


@lru_cache(maxsize=8)
def _c_header_u32_table(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = _ANY_DEFINE_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    if not out:
        raise RuntimeError(f"no #define constants parsed from {path}")
    return out


def c_header_u32(path: Path, symbol: str) -> int:
    """Return an integer ``#define`` from a PeakRDL-generated C header."""
    table = _c_header_u32_table(path)
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {path}") from exc


def cpu_ctrl_bm(symbol: str) -> int:
    """Return a ``CPU_CTRL__*_bm`` mask from ``cpu_ctrl.h``."""
    return c_header_u32(_CPU_CTRL_H, symbol)


def system_timer_octs_bm(symbol: str) -> int:
    """Return a ``SYSTEM_TIMER_OCTS__*_bm`` mask from ``system_timer_octs.h``."""
    return c_header_u32(_SYSTEM_TIMER_OCTS_H, symbol)


def wdt_bm(symbol: str) -> int:
    """Return a ``WDT__*_bm`` mask from ``wdt.h``."""
    return c_header_u32(_WDT_H, symbol)


def wdt_u32(symbol: str) -> int:
    """Return a ``WDT__*`` integer ``#define`` from ``wdt.h``."""
    return c_header_u32(_WDT_H, symbol)


def reset_unit_u32(symbol: str) -> int:
    """Return a ``RESET_UNIT__*`` integer ``#define`` from ``reset_unit.h``."""
    return c_header_u32(_RESET_UNIT_H, symbol)


def smc_base_config_u32(symbol: str) -> int:
    """Return an ``SMC_BASE_CONFIG__*`` integer ``#define`` from ``smc_base_config.h``."""
    return c_header_u32(_SMC_BASE_CONFIG_H, symbol)


def dfx_ctrl_status_u32(symbol: str) -> int:
    """Return a ``DFX_CTRL_STATUS__*`` integer ``#define`` from ``dfx_ctrl_status.h``."""
    return c_header_u32(_DFX_CTRL_STATUS_H, symbol)


def telemetry_receiver_u32(symbol: str) -> int:
    """Return a ``TELEMETRY_RECEIVER__*`` integer ``#define`` from ``telemetry_receiver.h``."""
    return c_header_u32(_TELEMETRY_RECEIVER_H, symbol)


def mailbox_u32(symbol: str) -> int:
    """Return an ``AXIL_MAILBOX__*`` integer ``#define`` from ``axil_mailbox.h``."""
    return c_header_u32(_AXIL_MAILBOX_H, symbol)


def smc_indexed_addr(symbol: str, idx: int = 0) -> int:
    """Return ``BASE + idx*STRIDE`` for an indexed ``SMC_TOP_*_BASE_ADDR`` macro."""
    table = _smc_indexed_table()
    try:
        base, stride = table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not an indexed macro in {_SMC_ADDR_H}") from exc
    return base + int(idx) * stride


def smc_indexed2_addr(symbol: str, outer: int = 0, inner: int = 0) -> int:
    """Return ``BASE + outer*S1 + inner*S2`` for a two-index ``SMC_TOP_*`` macro."""
    table = _smc_indexed2_table()
    try:
        base, s_outer, s_inner = table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not a two-index macro in {_SMC_ADDR_H}") from exc
    return base + int(outer) * s_outer + int(inner) * s_inner


def smc_indexed_stride(symbol: str) -> int:
    """Return stride for an indexed ``SMC_TOP_*_BASE_ADDR`` macro."""
    table = _smc_indexed_table()
    try:
        return table[symbol][1]
    except KeyError as exc:
        raise KeyError(f"{symbol} not an indexed macro in {_SMC_ADDR_H}") from exc


# Canonical smoke probe: CHIP_CONFIG.VERSION_LO
SMC_CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
SMC_CHIP_CONFIG_VERSION_LO_RESET = c_header_u32(
    _CHIP_CONFIG_H, "CHIP_CONFIG__VERSION_LO__VERSION_LO_reset"
)
SMC_CHIP_CONFIG_CHIP_ID = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR")


def smc_local_xbar_unmapped_gap() -> int:
    """Page-aligned hole between CORE3 WDT bank end and RESET_UNIT."""
    wdt_end = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR") + smc_addr(
        "SMC_TOP_SMC_CLUSTER_CORE3_WDT_SIZE"
    )
    reset = smc_addr("SMC_TOP_SMC_RESET_UNIT_BASE_ADDR")
    gap = ((wdt_end + reset) // 2) & ~0xFFF
    if not (wdt_end <= gap < reset):
        raise RuntimeError(
            f"unmapped gap 0x{gap:08x} not in [WDT end 0x{wdt_end:08x}, RESET_UNIT 0x{reset:08x})"
        )
    return gap


SMC_LOCAL_XBAR_UNMAPPED_GAP = smc_local_xbar_unmapped_gap()

# Inbound filter instance 0 (authoritative indexed map).
INBOUND_FILTER_CONFIG_SYM = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
INBOUND_FILTER_START_SYM = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
INBOUND_FILTER_END_SYM = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"
OUTBOUND_FILTER_CONFIG_SYM = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
OUTBOUND_FILTER_START_SYM = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
OUTBOUND_FILTER_END_SYM = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

INBOUND0_FILTER_CONFIG = smc_indexed_addr(INBOUND_FILTER_CONFIG_SYM, 0)
INBOUND0_START = smc_indexed_addr(INBOUND_FILTER_START_SYM, 0)
INBOUND0_END = smc_indexed_addr(INBOUND_FILTER_END_SYM, 0)
OUTBOUND0_FILTER_CONFIG = smc_indexed_addr(OUTBOUND_FILTER_CONFIG_SYM, 0)
OUTBOUND0_START = smc_indexed_addr(OUTBOUND_FILTER_START_SYM, 0)
OUTBOUND0_END = smc_indexed_addr(OUTBOUND_FILTER_END_SYM, 0)
INBOUND_FILTER_INST_STRIDE = smc_indexed_stride(INBOUND_FILTER_CONFIG_SYM)
