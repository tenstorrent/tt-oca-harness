# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helpers shared by the SMU composition and bring-up sequences.

Spec-derived constants live here so every composition leaf compares against
the same expected values: the SMU_SPEC.md Specifications and Configuration
Parameters tables, and the AMBA AXI4 channel field widths the crossbar struct
types are built from.
"""

from __future__ import annotations

from typing import Any

from cocotb.triggers import Timer

# SMU_SPEC.md "Specifications" / port_table.adoc.
LC_STATE_O_WIDTH = 8
LCC_DEMOTE_WIDTH = 2
NUM_INT_TO_SMC = 256
XTRIG_NUM_CTP = 16
XTRIG_NUM_INT_CT = 8
DTP_NUM_INT_CT = XTRIG_NUM_INT_CT + 2
NUM_SUBSYSTEMS = 32
SS_CONFIG_WIDTH = 32
SMN_IN_ID_WIDTH = 8
SMN_OUT_ID_WIDTH = 10
SUBSYS_IN_ID_WIDTH = 6
XBAR_ADDR_WIDTH = 56
XBAR_DATA_WIDTH = 64
XBAR_USER_WIDTH = 12
SEP_SEC_DISABLE_TOKEN_WIDTH = 256
SEP_OTP_PL_DEPTH = 3

# AMBA AXI4 channel field widths, plus the 6-bit atomic-operation field the
# crossbar's AW channel carries (SMU_SPEC.md: `ATOPs = 1'b0`).
_AXI_LEN = 8
_AXI_SIZE = 3
_AXI_BURST = 2
_AXI_LOCK = 1
_AXI_CACHE = 4
_AXI_PROT = 3
_AXI_QOS = 4
_AXI_REGION = 4
_AXI_RESP = 2
_AXI_LAST = 1
_AXI_ATOP = 6
_AXI_AX_COMMON = (
    XBAR_ADDR_WIDTH
    + _AXI_LEN
    + _AXI_SIZE
    + _AXI_BURST
    + _AXI_LOCK
    + _AXI_CACHE
    + _AXI_PROT
    + _AXI_QOS
    + _AXI_REGION
    + XBAR_USER_WIDTH
)


def axi_req_bits(id_width: int) -> int:
    """Packed width of a crossbar request struct for one ID width."""
    aw = id_width + _AXI_AX_COMMON + _AXI_ATOP
    w = XBAR_DATA_WIDTH + XBAR_DATA_WIDTH // 8 + _AXI_LAST + XBAR_USER_WIDTH
    ar = id_width + _AXI_AX_COMMON
    return aw + 1 + w + 1 + 1 + ar + 1 + 1


def axi_resp_bits(id_width: int) -> int:
    """Packed width of a crossbar response struct for one ID width."""
    b = id_width + _AXI_RESP + XBAR_USER_WIDTH
    r = id_width + XBAR_DATA_WIDTH + _AXI_RESP + _AXI_LAST + XBAR_USER_WIDTH
    return 1 + 1 + 1 + 1 + b + 1 + r


# smu_pkg::smu_cfg_t in declaration order, MSB first. The widths are the
# field types the SMU_SPEC.md Configuration Parameters table names; the
# values compared against them come from that table.
CFG_LAYOUT: tuple[tuple[str, int], ...] = (
    ("NUM_INT_TO_SMC", 32),
    ("JTAG_BSR_ENABLE", 1),
    ("JTAG_EXTEST_TRAIN_ENABLE", 1),
    ("JTAG_EXTEST_PULSE_ENABLE", 1),
    ("JTAG_INTEST_ENABLE", 1),
    ("JTAG_CLAMP_ENABLE", 1),
    ("JTAG_HIGHZ_ENABLE", 1),
    ("JTAG_RUNBIST_ENABLE", 1),
    ("JTAG_TMP_ENABLE", 1),
    ("JTAG_IC_RESET_ENABLE", 1),
    ("JTAG_SMC_DBG_ENABLE", 1),
    ("JTAG_STAP_IO_ENABLE", 1),
    ("JTAG_NUM_EXTRA_STAPS", 32),
    ("JTAG_IDCODE_MFR_ID", 11),
    ("JTAG_IDCODE_PART_NUM", 16),
    ("JTAG_IDCODE_SI_REV", 4),
    ("JTAG_OCH_VER", 8),
    ("XTRIG_INT_CT_MODE", XTRIG_NUM_INT_CT),
    ("SMC_OTP_RD_PL_DEPTH", 2),
    ("SMC_OTP_WR_PL_DEPTH", 2),
    ("SMC_RD_PL_DEPTH", 2),
    ("SMC_WR_PL_DEPTH", 2),
    ("SEP_KM_LATCHED_MEM_RDATA", 1),
    ("SEP_ABR_MASKING_EN", 1),
    ("SEP_ABR_SRAM_LATENCY", 32),
)
CFG_TOTAL_BITS = sum(width for _, width in CFG_LAYOUT)

# SMU_SPEC.md "Subsystem configuration" default column. XTRIG_INT_CT_MODE is
# config-dependent there and is supplied by the testlist as +xtrig_int_ct_mode.
CFG_SPEC_DEFAULTS: dict[str, int] = {
    "NUM_INT_TO_SMC": NUM_INT_TO_SMC,
    "JTAG_BSR_ENABLE": 1,
    "JTAG_EXTEST_TRAIN_ENABLE": 1,
    "JTAG_EXTEST_PULSE_ENABLE": 1,
    "JTAG_INTEST_ENABLE": 1,
    "JTAG_CLAMP_ENABLE": 1,
    "JTAG_HIGHZ_ENABLE": 1,
    "JTAG_RUNBIST_ENABLE": 1,
    "JTAG_TMP_ENABLE": 1,
    "JTAG_IC_RESET_ENABLE": 1,
    "JTAG_SMC_DBG_ENABLE": 1,
    "JTAG_STAP_IO_ENABLE": 1,
    "JTAG_NUM_EXTRA_STAPS": 1,
    "JTAG_IDCODE_MFR_ID": 0,
    "JTAG_IDCODE_PART_NUM": 0,
    "JTAG_IDCODE_SI_REV": 0,
    "JTAG_OCH_VER": 0,
    "SMC_OTP_RD_PL_DEPTH": 3,
    "SMC_OTP_WR_PL_DEPTH": 3,
    "SMC_RD_PL_DEPTH": 3,
    "SMC_WR_PL_DEPTH": 3,
    "SEP_KM_LATCHED_MEM_RDATA": 1,
    "SEP_ABR_MASKING_EN": 1,
    "SEP_ABR_SRAM_LATENCY": 1,
}


def decode_cfg(raw: int) -> dict[str, int]:
    """Split an elaborated smu_cfg_t value into its named fields."""
    fields: dict[str, int] = {}
    shift = CFG_TOTAL_BITS
    for name, width in CFG_LAYOUT:
        shift -= width
        fields[name] = (raw >> shift) & ((1 << width) - 1)
    return fields


def sample(signal: Any, name: str, *, allow_xz: bool = False) -> int:
    val = signal.value
    if hasattr(val, "is_resolvable") and not val.is_resolvable:
        if allow_xz:
            return 0
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


def hier(root: Any, path: str) -> Any:
    """Resolve a dotted hierarchical path, naming the first missing element."""
    node = root
    walked = []
    for part in path.split("."):
        walked.append(part)
        try:
            node = getattr(node, part)
        except Exception as exc:  # noqa: BLE001 - the handle's exception type varies
            raise AssertionError(f"hierarchy element {'.'.join(walked)} not found: {exc}") from exc
        if node is None:
            raise AssertionError(f"hierarchy element {'.'.join(walked)} not found")
    return node


def bit_width(handle: Any, name: str) -> int:
    try:
        return len(handle)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"{name} has no width: {exc}") from exc


async def count_transitions(signals: dict[str, Any], window_ns: int, step_ns: int = 1) -> dict:
    """Count level changes on each signal over ``window_ns`` at ``step_ns`` resolution."""
    last = {name: sample(sig, name) for name, sig in signals.items()}
    counts = {name: 0 for name in signals}
    for _ in range(window_ns // step_ns):
        await Timer(step_ns, unit="ns")
        for name, sig in signals.items():
            now = sample(sig, name)
            if now != last[name]:
                counts[name] += 1
                last[name] = now
    return counts


def parse_plusarg_int(name: str, *, required: bool = True, default: int | None = None) -> int:
    import cocotb

    raw = cocotb.plusargs.get(name)
    if raw is None:
        if required:
            raise AssertionError(f"missing required +{name}=<value> contract in the testlist entry")
        return int(default or 0)
    return int(str(raw), 0)
