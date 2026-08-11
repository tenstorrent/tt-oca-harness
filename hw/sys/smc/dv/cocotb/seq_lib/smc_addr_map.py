# SPDX-License-Identifier: Apache-2.0
"""Load SMC / DMA CSR addresses from generated PeakRDL C headers (authoritative map).

Mirrors ``smu_addr_map.py``: symbols come from
``hw/sys/smc/regs/gen/c/smc_addr.h`` and
``vendor/pulp-platform/idma/overlay/rdl/gen/c/dma_ctrl_addr.h`` (+ field masks
from ``smc_base_config.h`` / ``dma_ctrl.h``), never hand-copied in tests.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[6]
_SMC_ADDR_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "smc_addr.h"
_SMC_BASE_CFG_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h"
)
_DMA_CTRL_ADDR_H = (
    _REPO
    / "vendor"
    / "pulp-platform"
    / "idma"
    / "overlay"
    / "rdl"
    / "gen"
    / "c"
    / "dma_ctrl_addr.h"
)
_DMA_CTRL_H = (
    _REPO
    / "vendor"
    / "pulp-platform"
    / "idma"
    / "overlay"
    / "rdl"
    / "gen"
    / "c"
    / "dma_ctrl.h"
)
# Flattened EXTERNAL_MANDATORY / instance symbols not exported by PeakRDL smc_addr.h.
_BOOTROM_REGS_H = (
    _REPO / "hw" / "sys" / "smc" / "bootrom" / "prod" / "registers" / "smc_top_regs.h"
)

_SIMPLE_DEFINE_RE = re.compile(
    r"^\s*#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\s*$"
)
# Bootrom style: #define NAME (0xC0400100)
_PAREN_DEFINE_RE = re.compile(
    r"^\s*#define\s+(\w+)\s+\((0x[0-9A-Fa-f]+|\d+)\)\s*$"
)
# PeakRDL indexed macros, e.g.:
#   #define FOO_BASE_ADDR(idx) (0xC0015000 + (idx * 0x00000020))
# Optional trailing space before the outer closing paren is allowed.
_INDEXED_DEFINE_RE = re.compile(
    r"^\s*#define\s+(\w+)\(\w+\)\s+\((0x[0-9A-Fa-f]+)\s*\+\s*\(\w+\s*\*\s*"
    r"(0x[0-9A-Fa-f]+)\)\s*\)\s*$"
)


@lru_cache(maxsize=1)
def _parse_simple_defines(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = _SIMPLE_DEFINE_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    if not out:
        raise RuntimeError(f"no #define constants parsed from {path}")
    return out


@lru_cache(maxsize=1)
def _parse_indexed_bases(path: Path) -> dict[str, tuple[int, int]]:
    """Return {name: (base, stride)} for PeakRDL ``NAME(idx) (base + (idx * stride))``."""
    text = path.read_text(encoding="utf-8")
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        m = _INDEXED_DEFINE_RE.match(line)
        if m:
            out[m.group(1)] = (int(m.group(2), 0), int(m.group(3), 0))
    return out


@lru_cache(maxsize=1)
def _parse_paren_defines(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = _PAREN_DEFINE_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    if not out:
        raise RuntimeError(f"no parenthesized #define constants parsed from {path}")
    return out


def smc_addr(symbol: str) -> int:
    """Return a ``SMC_TOP_*`` absolute address from ``smc_addr.h``."""
    table = _parse_simple_defines(_SMC_ADDR_H)
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {_SMC_ADDR_H}") from exc


def smc_indexed_addr(symbol: str, idx: int = 0) -> int:
    """Evaluate a PeakRDL indexed ``SMC_TOP_*_BASE_ADDR(idx)`` macro."""
    table = _parse_indexed_bases(_SMC_ADDR_H)
    try:
        base, stride = table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol}(idx) not in {_SMC_ADDR_H}") from exc
    return base + idx * stride


def smc_bootrom_addr(symbol: str) -> int:
    """Return a flattened absolute from bootrom ``smc_top_regs.h``."""
    table = _parse_paren_defines(_BOOTROM_REGS_H)
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {_BOOTROM_REGS_H}") from exc


def external_gpio_ctrl_addr(idx: int) -> int:
    """EXTERNAL_MANDATORY GPIO_CTRL_N CONTROL (bootrom map; not in PeakRDL)."""
    return smc_bootrom_addr(
        f"SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_{idx}__CONTROL_BASE_ADDR"
    )


@lru_cache(maxsize=1)
def external_gpio_ctrl_indices() -> tuple[int, ...]:
    """Sorted GPIO_CTRL instance indices present in the bootrom map."""
    table = _parse_paren_defines(_BOOTROM_REGS_H)
    prefix = "SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_"
    suffix = "__CONTROL_BASE_ADDR"
    idxs: list[int] = []
    for name in table:
        if name.startswith(prefix) and name.endswith(suffix):
            mid = name[len(prefix) : -len(suffix)]
            if mid.isdigit():
                idxs.append(int(mid))
    if not idxs:
        raise RuntimeError("no EXTERNAL_MANDATORY GPIO_CTRL_* in bootrom map")
    return tuple(sorted(idxs))


def dma_ctrl_offset(symbol: str) -> int:
    """Return a ``DMA_CTRL_*_BASE_ADDR`` offset from ``dma_ctrl_addr.h``."""
    table = _parse_simple_defines(_DMA_CTRL_ADDR_H)
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {_DMA_CTRL_ADDR_H}") from exc


def _field_mask(path: Path, symbol: str) -> int:
    table = _parse_simple_defines(path)
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {path}") from exc


# --- Absolute addresses used by SMC clock-gating / DMA activity tests ---
CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)

DMA_CTRL_BASE = smc_addr("SMC_TOP_DMA_CTRL_BASE_ADDR")

DMA_CTRL_CONFIG = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_CONFIG_BASE_ADDR")
DMA_CTRL_STATUS_0 = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_STATUS_0_BASE_ADDR")
DMA_CTRL_NEXT_ID_0 = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_NEXT_ID_0_BASE_ADDR")
DMA_CTRL_DONE_0 = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DONE_0_BASE_ADDR")
DMA_CTRL_DST_ADDRESS_LO = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR"
)
DMA_CTRL_DST_ADDRESS_HI = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_DST_ADDRESS_HI_BASE_ADDR"
)
DMA_CTRL_SRC_ADDRESS_LO = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_SRC_ADDRESS_LO_BASE_ADDR"
)
DMA_CTRL_SRC_ADDRESS_HI = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_SRC_ADDRESS_HI_BASE_ADDR"
)
DMA_CTRL_LENGTH_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_LENGTH_LO_BASE_ADDR")
DMA_CTRL_LENGTH_HI = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_LENGTH_HI_BASE_ADDR")
DMA_CTRL_DST_STRIDE_LO = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_DST_STRIDE_LO_BASE_ADDR"
)
DMA_CTRL_DST_STRIDE_HI = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_DST_STRIDE_HI_BASE_ADDR"
)
DMA_CTRL_SRC_STRIDE_LO = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_SRC_STRIDE_LO_BASE_ADDR"
)
DMA_CTRL_SRC_STRIDE_HI = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_SRC_STRIDE_HI_BASE_ADDR"
)
DMA_CTRL_NUM_REPETITIONS_LO = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_NUM_REPETITIONS_LO_BASE_ADDR"
)
DMA_CTRL_NUM_REPETITIONS_HI = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_NUM_REPETITIONS_HI_BASE_ADDR"
)

INBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
INBOUND0_START = smc_indexed_addr(
    "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0
)
INBOUND0_END = smc_indexed_addr(
    "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0
)
OUTBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
OUTBOUND0_START = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0
)
OUTBOUND0_END = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0
)

# Field masks / bit positions from generated block headers.
DMA_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__DMA_CG_EN_bm"
)
ZEROER_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__ZEROER_CG_EN_bm"
)
CG_HYST_MASK = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__CG_HYSTERESIS_bm"
)
CG_HYST_SHIFT = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__CG_HYSTERESIS_bp"
)
DMA_CONFIG_ENABLED_ND = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__ENABLED_ND_bm")

# Zeroer CSR absolute addresses (generated smc_addr.h).
ZEROER_CTRL_DEST_ADDR = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")
ZEROER_CTRL_SIZE = smc_addr("SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR")
ZEROER_CTRL_STATUS = smc_addr("SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR")

# Field masks used by I2C / telemetry sequences.
I2C_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I2C_CG_EN_bm"
)
I3C_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I3C_CG_EN_bm"
)
UART_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__UART_CG_EN_bm"
)
TELEMETRY_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__TELEMETRY_CG_EN_bm"
)

# GPIO_INTF meta from PeakRDL.
GPIO_INTF_NUM = smc_addr("SMC_TOP_GPIO_INTF_NUM")
GPIO_INTF_STRIDE = smc_addr("SMC_TOP_GPIO_INTF_STRIDE")
