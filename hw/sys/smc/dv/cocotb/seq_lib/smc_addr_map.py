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

# --- smc_local_fabric address fold -----------------------------------------
# Every request entering the local fabric has its upper 7 address bits replaced
# by LOCAL_BASE[31:25]:
#   hw/sys/smc/rtl/smc_fabric/smc_local_fabric/rtl/smc_local_fabric.sv:66-78
#   sep_in_req_masked.ar.addr = {local_base_addr_i[31:25],
#                                sep_in_axi_req_i.ar.addr[24:0]};
# so only addr[24:0] of a SEP_IN address survives to the decoder. `LOCAL_BASE`
# is `SMC_BASE_CONFIG.LOCAL_BASE` (smc_base.sv:381 -> smc_fabric.sv:141); its
# reset is taken from the generated RDL header, not hand-copied, so a map change
# moves the model with the hardware ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
LOCAL_FABRIC_KEEP_MASK = 0x01FF_FFFF     # addr[24:0] survive the fold
LOCAL_FABRIC_REPLACE_MASK = 0xFE00_0000  # addr[31:25] are overwritten
LOCAL_BASE_RESET = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset"
)


def local_fabric_masked_addr(addr: int, local_base: int | None = None) -> int:
    """Address a SEP_IN/system/local request arrives at after the fold above."""
    base = LOCAL_BASE_RESET if local_base is None else local_base
    return (base & LOCAL_FABRIC_REPLACE_MASK) | (addr & LOCAL_FABRIC_KEEP_MASK)


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
        field = name[len(prefix): -len(suffix)]
        word |= value << table[f"{prefix}{field}_bp"]
        seen += 1
    if not seen:
        raise KeyError(f"no {prefix}*{suffix} fields in {header}")
    return word


# SMC_BASE_CONFIG reset words used as goldens by the fabric/decode testcases.
GLOBAL_BASE_RESET = reg_reset_word(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "GLOBAL_BASE"
)
REGION_SIZE_RESET = reg_reset_word(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "REGION_SIZE"
)
CLOCK_GATE_CONTROL_RESET = reg_reset_word(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG", "CLOCK_GATE_CONTROL"
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

_GPIO_INTF_H = (
    _REPO / "hw" / "ip" / "gpio" / "regs" / "gen" / "c" / "gpio_intf.h"
)


def gpio_intf_u32(symbol: str) -> int:
    """Field mask/position from generated ``gpio_intf.h``."""
    return _field_mask(_GPIO_INTF_H, symbol)


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


_CPU_CTRL_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"
)


def cpu_ctrl_u32(symbol: str) -> int:
    """Field mask from generated ``cpu_ctrl.h``."""
    return _field_mask(_CPU_CTRL_H, symbol)


_RESET_UNIT_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "reset_unit.h"
)


def reset_unit_u32(symbol: str) -> int:
    """Field mask from generated ``reset_unit.h``."""
    return _field_mask(_RESET_UNIT_H, symbol)


_SMC_PKG_SV = _REPO / "hw" / "sys" / "smc" / "rtl" / "smc_pkg.sv"
_PACKED_STRUCT_RE = re.compile(
    r"typedef\s+struct\s+packed\s*\{(.*?)\}\s*(\w+)\s*;",
    re.S,
)
_LOGIC_VEC_RE = re.compile(
    r"logic\s+\[(\d+)\s*:\s*0\]\s+(\w+)\s*;"
)
_LOGIC_BIT_RE = re.compile(r"logic\s+(\w+)\s*;")
_NESTED_RE = re.compile(r"(\w+)\s+(\w+)\s*;")


@lru_cache(maxsize=1)
def _jtag_smc_reset_ctrl_layout() -> dict[str, tuple[int, int]]:
    """Leaf name → (lsb, width) in packed ``jtag_smc_reset_ctrl_t`` from smc_pkg.sv.

    SystemVerilog packed structs put the first declared field at the MSB.
    Nested ``ovrd``/``val`` types are flattened; vector index 0 is the field LSB.
    """
    text = _SMC_PKG_SV.read_text(encoding="utf-8")
    structs: dict[str, list[tuple[str, int | str]]] = {}
    for body, name in _PACKED_STRUCT_RE.findall(text):
        fields: list[tuple[str, int | str]] = []
        for raw in body.splitlines():
            line = raw.split("//", 1)[0].strip()
            if not line:
                continue
            m = _LOGIC_VEC_RE.search(line)
            if m:
                fields.append((m.group(2), int(m.group(1)) + 1))
                continue
            m = _LOGIC_BIT_RE.search(line)
            if m:
                fields.append((m.group(1), 1))
                continue
            m = _NESTED_RE.search(line)
            if m and m.group(1) not in ("logic", "typedef"):
                fields.append((m.group(2), m.group(1)))
        if fields:
            structs[name] = fields
    if "jtag_smc_reset_ctrl_t" not in structs:
        raise RuntimeError(f"jtag_smc_reset_ctrl_t not in {_SMC_PKG_SV}")

    def _flatten(type_name: str) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for fname, spec in structs[type_name]:
            if isinstance(spec, int):
                out.append((fname, spec))
            else:
                out.extend(_flatten(spec))
        return out

    leaves = _flatten("jtag_smc_reset_ctrl_t")
    total = sum(width for _, width in leaves)
    layout: dict[str, tuple[int, int]] = {}
    bit = total - 1
    for fname, width in leaves:
        lsb = bit - width + 1
        layout[fname] = (lsb, width)
        bit = lsb - 1
    return layout


def jtag_smc_reset_ctrl_width() -> int:
    """``$bits(jtag_smc_reset_ctrl_t)`` from ``smc_pkg.sv``."""
    return sum(width for _, width in _jtag_smc_reset_ctrl_layout().values())


def jtag_smc_reset_ctrl_bit(leaf: str, idx: int = 0) -> int:
    """Packed bit index of ``jtag_smc_reset_ctrl_t.<leaf>[idx]`` from smc_pkg.sv."""
    layout = _jtag_smc_reset_ctrl_layout()
    try:
        lsb, width = layout[leaf]
    except KeyError as exc:
        raise KeyError(f"{leaf} not in jtag_smc_reset_ctrl_t") from exc
    if idx < 0 or idx >= width:
        raise AssertionError(f"{leaf}[{idx}] out of range width={width}")
    return lsb + idx



_EFUSE_IFC_H = (
    _REPO / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_interface_ctrl.h"
)


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
HANG_DET_THR_VALUE = hang_det_ctrl_u32(
    "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_bm"
)

HANG_DET_SYS_AXI_CTRL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR"
)
HANG_DET_SEP_AXI_CTRL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR"
)
HANG_DET_DATA_ACCEL_CTRL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR"
)
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

_DFX_CTRL_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "dfx_ctrl_status.h"
)


def dfx_status_u32(symbol: str) -> int:
    """Field mask from generated ``dfx_ctrl_status.h`` STATUS."""
    return _field_mask(_DFX_CTRL_H, symbol)


DFX_STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
DFX_MEM_REPAIR_DONE = dfx_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_DONE_bm")
DFX_MEM_REPAIR_SUCCESS = dfx_status_u32(
    "DFX_CTRL_STATUS__STATUS__MEM_REPAIR_SUCCESS_bm"
)
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
DFX_STATUS_IDLE = (
    DFX_MEM_REPAIR_DONE
    | DFX_MEM_REPAIR_SUCCESS
    | DFX_MBIST_DONE
    | DFX_MBIST_PASS
)
