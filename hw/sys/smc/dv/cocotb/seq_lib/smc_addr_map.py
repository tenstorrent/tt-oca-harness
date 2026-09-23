# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
    _REPO / "vendor" / "pulp-platform" / "idma" / "overlay" / "rdl" / "gen" / "c" / "dma_ctrl.h"
)
# Flattened EXTERNAL_MANDATORY / instance symbols not exported by PeakRDL smc_addr.h.
_BOOTROM_REGS_H = _REPO / "hw" / "sys" / "smc" / "bootrom" / "prod" / "registers" / "smc_top_regs.h"

_SIMPLE_DEFINE_RE = re.compile(r"^\s*#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\s*$")
# Bootrom style: #define NAME (0xC0400100)
_PAREN_DEFINE_RE = re.compile(r"^\s*#define\s+(\w+)\s+\((0x[0-9A-Fa-f]+|\d+)\)\s*$")
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


def smc_addr_symbols(pattern: str) -> tuple[str, ...]:
    """Return every ``SMC_TOP_*`` symbol in ``smc_addr.h`` matching ``pattern`` (a full-match regex)."""
    rx = re.compile(pattern)
    return tuple(name for name in _parse_simple_defines(_SMC_ADDR_H) if rx.fullmatch(name))


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
    return smc_bootrom_addr(f"SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_{idx}__CONTROL_BASE_ADDR")


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
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

# --- Local-alias aperture fold ---------------------------------------------
# Every request entering the SMC local fabric is folded into the local-alias
# aperture, which is `LOCAL_BASE`-aligned and `REGION_SIZE` bytes long: the
# fabric keeps the low address bits under `REGION_SIZE - 1` and prefixes
# `LOCAL_BASE` above them. Authority: the `SMC_BASE_CONFIG.REGION_SIZE` field
# description in the RDL (the mask is `(size - 1)`, so the size must be a
# non-zero power of two and both bases aligned to it) and
# hw/sys/smc/doc/fabric.adoc "Local and Remote Resource Access". Both operands
# are the generated RDL resets, so the model moves with the register map
# ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
LOCAL_BASE_RESET = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
_REGION_SIZE_FIELD_RESET = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")


def local_fabric_keep_mask(region_size: int = _REGION_SIZE_FIELD_RESET) -> int:
    """Address bits that survive the local-alias fold for ``region_size``."""
    assert region_size > 0 and region_size & (region_size - 1) == 0, (
        f"REGION_SIZE 0x{region_size:x} is not a non-zero power of two; the RDL forbids "
        "it because the fabric mask is (size - 1)"
    )
    return region_size - 1


LOCAL_FABRIC_KEEP_MASK = local_fabric_keep_mask()
LOCAL_FABRIC_REPLACE_MASK = 0xFFFF_FFFF & ~LOCAL_FABRIC_KEEP_MASK


def local_fabric_masked_addr(
    addr: int, local_base: int | None = None, region_size: int | None = None
) -> int:
    """Address a SEP_IN/system/local request arrives at after the fold above."""
    base = LOCAL_BASE_RESET if local_base is None else local_base
    keep = local_fabric_keep_mask(_REGION_SIZE_FIELD_RESET if region_size is None else region_size)
    assert base & keep == 0, f"LOCAL_BASE 0x{base:x} is not aligned to REGION_SIZE 0x{keep + 1:x}"
    return (base & 0xFFFF_FFFF) | (addr & keep)


def reg_reset_word(header: Path, block: str, reg: str) -> int:
    """Compose a register's reset word from its generated ``_reset``/``_bp`` fields.

    Every field the RDL declares contributes, so the golden tracks the RDL
    instead of being a hand-transcribed literal that has to be re-checked by a
    reader ([EXACT-EXPECTATION] / [INDEPENDENT-EXPECTED-MODEL]).
    """
    table = _parse_simple_defines(header)
    prefix = f"{block}__{reg}__"
    suffix = "_reset"
    word = 0
    seen = 0
    for name, value in table.items():
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        field = name[len(prefix) : -len(suffix)]
        word |= value << table[f"{prefix}{field}_bp"]
        seen += 1
    if not seen:
        raise KeyError(f"no {prefix}*{suffix} fields in {header}")
    return word


# SMC_BASE_CONFIG reset words used as goldens by the fabric/decode testcases.
GLOBAL_BASE_RESET = reg_reset_word(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "GLOBAL_BASE")
LOCAL_BASE_RESET = reg_reset_word(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "LOCAL_BASE")

# The window table the register generator writes from the RDL address map and
# `doc/memmap.adoc` includes: one row per unit, `|BASE + <lo> - BASE + <hi> |...|<unit>|`.
_MEMORY_MAP_ADOC = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "adoc" / "memory_map.adoc"
_WINDOW_ROW = re.compile(
    r"^\|BASE \+ (0x[0-9A-Fa-f]+) [-\u2013] BASE \+ (0x[0-9A-Fa-f]+) \|[^|]*\|[^|]*\|([^|]+)\|"
)


def generated_window(unit: str) -> tuple[int, int]:
    """Return ``(first, last)`` offsets of the window the generated memory map gives ``unit``."""
    for line in _MEMORY_MAP_ADOC.read_text().splitlines():
        m = _WINDOW_ROW.match(line)
        if m and m.group(3).strip() == unit:
            return int(m.group(1), 16), int(m.group(2), 16)
    raise KeyError(f"{unit} has no window row in {_MEMORY_MAP_ADOC}")


REGION_SIZE_RESET = reg_reset_word(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "REGION_SIZE")
CLOCK_GATE_CONTROL_RESET = reg_reset_word(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "CLOCK_GATE_CONTROL")

DMA_CTRL_BASE = smc_addr("SMC_TOP_DMA_CTRL_BASE_ADDR")

DMA_CTRL_CONFIG = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_CONFIG_BASE_ADDR")
DMA_CTRL_STATUS_0 = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_STATUS_0_BASE_ADDR")
DMA_CTRL_NEXT_ID_0 = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_NEXT_ID_0_BASE_ADDR")
DMA_CTRL_DONE_0 = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DONE_0_BASE_ADDR")
DMA_CTRL_DST_ADDRESS_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
DMA_CTRL_DST_ADDRESS_HI = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DST_ADDRESS_HI_BASE_ADDR")
DMA_CTRL_SRC_ADDRESS_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_SRC_ADDRESS_LO_BASE_ADDR")
DMA_CTRL_SRC_ADDRESS_HI = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_SRC_ADDRESS_HI_BASE_ADDR")
DMA_CTRL_LENGTH_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_LENGTH_LO_BASE_ADDR")
DMA_CTRL_LENGTH_HI = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_LENGTH_HI_BASE_ADDR")
DMA_CTRL_DST_STRIDE_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DST_STRIDE_LO_BASE_ADDR")
DMA_CTRL_DST_STRIDE_HI = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DST_STRIDE_HI_BASE_ADDR")
DMA_CTRL_SRC_STRIDE_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_SRC_STRIDE_LO_BASE_ADDR")
DMA_CTRL_SRC_STRIDE_HI = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_SRC_STRIDE_HI_BASE_ADDR")
DMA_CTRL_NUM_REPETITIONS_LO = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_NUM_REPETITIONS_LO_BASE_ADDR"
)
DMA_CTRL_NUM_REPETITIONS_HI = DMA_CTRL_BASE + dma_ctrl_offset(
    "DMA_CTRL_NUM_REPETITIONS_HI_BASE_ADDR"
)

INBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
INBOUND0_START = smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0)
INBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)
OUTBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
OUTBOUND0_START = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0)
OUTBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)

# Field masks / bit positions from generated block headers.
DMA_CG_EN = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__DMA_CG_EN_bm")
ZEROER_CG_EN = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__ZEROER_CG_EN_bm")
CG_HYST_MASK = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__CG_HYSTERESIS_bm")
CG_HYST_SHIFT = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__CG_HYSTERESIS_bp"
)
DMA_CONFIG_ENABLED_ND = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__ENABLED_ND_bm")

# Zeroer CSR absolute addresses (generated smc_addr.h).
ZEROER_CTRL_DEST_ADDR = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")
ZEROER_CTRL_SIZE = smc_addr("SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR")
ZEROER_CTRL_STATUS = smc_addr("SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR")

# Field masks used by I2C / telemetry sequences.
I2C_CG_EN = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I2C_CG_EN_bm")
I3C_CG_EN = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I3C_CG_EN_bm")
UART_CG_EN = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__UART_CG_EN_bm")
TELEMETRY_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__TELEMETRY_CG_EN_bm"
)

# GPIO_INTF meta from PeakRDL.
GPIO_INTF_NUM = smc_addr("SMC_TOP_GPIO_INTF_NUM")
GPIO_INTF_STRIDE = smc_addr("SMC_TOP_GPIO_INTF_STRIDE")

_GPIO_INTF_H = _REPO / "hw" / "ip" / "gpio" / "regs" / "gen" / "c" / "gpio_intf.h"


def gpio_intf_u32(symbol: str) -> int:
    """Field mask/position from generated ``gpio_intf.h``."""
    return _field_mask(_GPIO_INTF_H, symbol)


_UART_16550_DL_H = (
    _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_dl.h"
)
_UART_16550_DL_ADDR_H = (
    _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_dl_addr.h"
)


def uart_16550_dl_u32(symbol: str) -> int:
    """Field mask/position/reset from generated ``uart_16550_dl.h``."""
    return _field_mask(_UART_16550_DL_H, symbol)


def uart_16550_dl_offset(symbol: str) -> int:
    """Register offset inside the divisor-latch window from ``uart_16550_dl_addr.h``."""
    return _field_mask(_UART_16550_DL_ADDR_H, symbol)


_GPIO_POC_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "gpio_poc_pbias_ctrl.h"
)


def gpio_poc_u32(symbol: str) -> int:
    """Field mask/reset from generated ``gpio_poc_pbias_ctrl.h``."""
    return _field_mask(_GPIO_POC_H, symbol)


_SMC_EFUSE_MAP_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_efuse_map.h"
)


def smc_efuse_map_u32(symbol: str) -> int:
    """Field mask from generated ``smc_efuse_map.h``."""
    return _field_mask(_SMC_EFUSE_MAP_H, symbol)


_CPU_CTRL_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"


def cpu_ctrl_u32(symbol: str) -> int:
    """Field mask from generated ``cpu_ctrl.h``."""
    return _field_mask(_CPU_CTRL_H, symbol)


_RESET_UNIT_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "reset_unit.h"


def reset_unit_u32(symbol: str) -> int:
    """Field mask from generated ``reset_unit.h``."""
    return _field_mask(_RESET_UNIT_H, symbol)


# --- JTAG IC_RESET SMC slice (`jtag_reset_ctrl_i`) ---------------------------
# DV-owned layout of the SMC slice of the IEEE 1149.1 IC_RESET TDR. Shape:
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc "IC_RESET Support" -- the slice is
# a packed struct of an `.ovrd` half (active-high JTAG-override flags) above a
# `.val` half (active-low reset values) of identical width, one pair per
# controlled reset -- and hw/sys/dtp/doc/port_table.adoc `jtag_ic_reset_smc_o`,
# which sizes each half to the SMC reset-control set (hw/sys/smc/doc/
# port_table.adoc `jtag_reset_ctrl_i`). Members: the warm / cool / cold reset
# levels of hw/sys/smc/doc/clk_rst.adoc, the fuse reset of hw/sys/smc/doc/
# port_table.adoc `smc_fuse_reset_n_delayed_o`, plus the per-subsystem warm
# and cold vectors, whose widths are the RDL fields RESET_UNIT.SS_WARM_RESET_N /
# SS_COLD_RESET_N (generated `reset_unit.h`). No document fixes the order of
# the leaves inside a half, so that order is a DV-owned golden.
# smc_jtag_reset_ctrl_test drives `cool_reset_n` and `ss_warm_reset_n[0]` one
# at a time and requires the matching reset pin -- and only that pin -- to
# move, which fails on a wrong position of either leaf, a swapped half or a
# wrong slice width. The positions of the other leaves are not exercised by
# any test.
JTAG_RESET_CTRL_HALVES: tuple[str, ...] = ("ovrd", "val")  # MSB half first
JTAG_RESET_CTRL_LEAVES: tuple[tuple[str, int], ...] = (  # MSB leaf first
    ("ss_warm_reset_n", reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_bw")),
    ("ss_cold_reset_n", reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_bw")),
    ("cold_reset_n", 1),
    ("cool_reset_n", 1),
    ("warm_reset_n", 1),
    ("fuse_reset_n", 1),
)


def jtag_smc_reset_ctrl_width() -> int:
    """Packed width of the SMC IC_RESET slice: both halves of the DV-owned table."""
    return len(JTAG_RESET_CTRL_HALVES) * sum(width for _, width in JTAG_RESET_CTRL_LEAVES)


@lru_cache(maxsize=1)
def _jtag_smc_reset_ctrl_layout() -> dict[str, tuple[int, int]]:
    """Leaf name (``<leaf>_ovrd`` / ``<leaf>_val``) -> (lsb, width) in the packed slice."""
    layout: dict[str, tuple[int, int]] = {}
    bit = jtag_smc_reset_ctrl_width() - 1
    for half in JTAG_RESET_CTRL_HALVES:
        for leaf, width in JTAG_RESET_CTRL_LEAVES:
            lsb = bit - width + 1
            layout[f"{leaf}_{half}"] = (lsb, width)
            bit = lsb - 1
    assert bit == -1, "JTAG reset-control table does not tile its packed width"
    return layout


def jtag_smc_reset_ctrl_bit(leaf: str, idx: int = 0) -> int:
    """Packed bit index of ``jtag_reset_ctrl_i.<leaf>[idx]`` from the DV-owned table."""
    layout = _jtag_smc_reset_ctrl_layout()
    try:
        lsb, width = layout[leaf]
    except KeyError as exc:
        raise KeyError(f"{leaf} not in the JTAG reset-control table") from exc
    if idx < 0 or idx >= width:
        raise AssertionError(f"{leaf}[{idx}] out of range width={width}")
    return lsb + idx


_EFUSE_IFC_H = _REPO / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_interface_ctrl.h"


def efuse_ifc_u32(symbol: str) -> int:
    """Field mask from generated ``efuse_interface_ctrl.h``."""
    return _field_mask(_EFUSE_IFC_H, symbol)


def hang_det_ctrl_u32(symbol: str) -> int:
    """Field mask from generated ``smc_base_config.h`` HANG_DET_CTRL."""
    return _field_mask(_SMC_BASE_CFG_H, symbol)


HANG_DET_ENABLE = hang_det_ctrl_u32("SMC_BASE_CONFIG__HANG_DET_CTRL__ENABLE_bm")
HANG_DET_IRQ_EN = hang_det_ctrl_u32("SMC_BASE_CONFIG__HANG_DET_CTRL__IRQ_EN_bm")
HANG_DET_IRQ_TEST = hang_det_ctrl_u32("SMC_BASE_CONFIG__HANG_DET_CTRL__IRQ_TEST_bm")
HANG_DET_FIRE = HANG_DET_ENABLE | HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST
HANG_DET_ARMED = HANG_DET_ENABLE | HANG_DET_IRQ_EN
HANG_DET_THR_VALUE = hang_det_ctrl_u32("SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_bm")

HANG_DET_SYS_AXI_CTRL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR")
HANG_DET_SEP_AXI_CTRL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR")
HANG_DET_DATA_ACCEL_CTRL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR")
HANG_DET_SEP_AXI_TIMEOUT = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"
)
HANG_DET_SYS_AXI_TIMEOUT = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"
)
HANG_DET_DATA_ACCEL_TIMEOUT = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"
)

SPM_MEMORY_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_MEMORY_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")

_DFX_CTRL_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "dfx_ctrl_status.h"


def dfx_status_u32(symbol: str) -> int:
    """Field mask from generated ``dfx_ctrl_status.h`` STATUS."""
    return _field_mask(_DFX_CTRL_H, symbol)


DFX_STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
DFX_MEM_REPAIR_DONE = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_DONE_bm")
DFX_MEM_REPAIR_SUCCESS = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_SUCCESS_bm")
DFX_MEM_REPAIR_ABORT = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_ABORT_bm")
DFX_MBIST_DONE = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_DONE_bm")
DFX_MBIST_PASS = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_PASS_bm")
DFX_MBIST_ABORT = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_ABORT_bm")
# The STATUS_SMU word an SMC bench shows when neither engine has aborted. The
# bit POSITIONS are authoritative (generated `dfx_ctrl_status.h`); the choice of
# which four are set is a property of THIS bench, not of the DFX block:
# `hw/sys/smc/dv/tb/tb_top.sv:1314-1318` ties `mem_repair_done_i`,
# `mem_repair_success_i`, `mbist_done_i` and `mbist_pass_i` to `1'b1` (without
# an external BISR/MBIST agent the boot sequencer would otherwise wait forever),
# and leaves the two abort inputs to the sequences. Any testcase using this
# constant as a golden is asserting the tie-off block above, so a change there
# must move this constant with it.
DFX_STATUS_IDLE = DFX_MEM_REPAIR_DONE | DFX_MEM_REPAIR_SUCCESS | DFX_MBIST_DONE | DFX_MBIST_PASS


# --- RDL-declared windows and deadspace -------------------------------------
# The generated map is the only authority for which SMC addresses hold a
# register or memory. Everything else inside the map is deadspace, which the
# RDL cannot express and is therefore derived from the neighbouring windows
# rather than listed ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
_ROOT_BASE_SYMBOL = "SMC_TOP_BASE_ADDR"


@lru_cache(maxsize=1)
def smc_rdl_windows() -> tuple[tuple[int, int], ...]:
    """Merged, ascending ``[base, end)`` ranges of every RDL-declared SMC block.

    Built from every ``SMC_TOP_*_BASE_ADDR`` / ``_SIZE`` pair and every indexed
    ``_BASE_ADDR(idx)`` macro with its ``_TOTAL_SIZE`` (or ``_NUM`` and stride)
    in ``smc_addr.h``. The root addrmap's own extent is excluded: it spans the
    holes this function exists to expose.
    """
    defs = _parse_simple_defines(_SMC_ADDR_H)
    spans: list[tuple[int, int]] = []
    for name, base in defs.items():
        if not name.endswith("_BASE_ADDR") or name == _ROOT_BASE_SYMBOL:
            continue
        size = defs.get(name[: -len("_BASE_ADDR")] + "_SIZE")
        if size:
            spans.append((base, base + size))
    for name, (base, stride) in _parse_indexed_bases(_SMC_ADDR_H).items():
        prefix = name[: -len("_BASE_ADDR")]
        total = defs.get(f"{prefix}_TOTAL_SIZE")
        if total is None:
            num = defs[f"{prefix}_NUM"]
            total = (num - 1) * stride + defs.get(f"{prefix}_SIZE", stride)
        spans.append((base, base + total))
    if not spans:
        raise RuntimeError(f"no block windows parsed from {_SMC_ADDR_H}")
    merged: list[tuple[int, int]] = []
    for base, end in sorted(spans):
        if merged and base <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((base, end))
    return tuple(merged)


@lru_cache(maxsize=1)
def smc_deadspace_ranges() -> tuple[tuple[int, int], ...]:
    """Gaps ``[base, end)`` between the RDL windows; nothing in the map lives there."""
    windows = smc_rdl_windows()
    return tuple((lo_end, hi_base) for (_, lo_end), (hi_base, _) in zip(windows, windows[1:]))


def smc_map_extent() -> tuple[int, int]:
    """``[first window base, last window end)`` -- the span the RDL map describes."""
    windows = smc_rdl_windows()
    return windows[0][0], windows[-1][1]


def smc_addr_is_deadspace(addr: int) -> bool:
    """True when no RDL-declared SMC window contains ``addr``."""
    return not any(base <= addr < end for base, end in smc_rdl_windows())


def check_rdl_windows() -> None:
    """Self-check of the window derivation against the root addrmap.

    Every window must lie inside ``SMC_TOP`` and the last one must end where
    the root's own generated size says the map ends. This catches a window
    parsed past the end of the map and any mis-parse that moves the last
    window's end; it cannot catch a base, size or instance count that is wrong
    but still inside the root (``SMC_TOP_BASE_ADDR`` is 0, so only the upper
    bound bites), and overlap between blocks is not checkable from the header:
    register-level macros legitimately interleave (indexed arrays), so
    overlapping spans are merged, not rejected.
    """
    defs = _parse_simple_defines(_SMC_ADDR_H)
    root_lo = defs[_ROOT_BASE_SYMBOL]
    root_hi = root_lo + defs[_ROOT_BASE_SYMBOL[: -len("_BASE_ADDR")] + "_SIZE"]
    windows = smc_rdl_windows()
    for base, end in windows:
        assert root_lo <= base < end <= root_hi, (
            f"RDL window {base:#x}-{end:#x} lies outside the root addrmap {root_lo:#x}-{root_hi:#x}"
        )
    assert windows[-1][1] == root_hi, (
        f"last RDL window ends at {windows[-1][1]:#x} but the root addrmap size ends the map at "
        f"{root_hi:#x}"
    )
