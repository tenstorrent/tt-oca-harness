# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helpers shared by the SMU composition and bring-up sequences.

The expected values every composition leaf compares against live here, with
the source of each one named. Two kinds of source appear below and they do not
carry the same weight:

* ``hw/sys/smu/doc/port_table.adoc`` -- the SMU Port Declaration. It states each
  port's presence, direction, type, width expression and semantics, and it is
  the only SMU specification in this tree a reader can open.
* ``hw/sys/smu/rtl/smu_pkg.sv``, ``hw/sys/smu/rtl/smu_axi_xbar_pkg.sv`` and the
  vendored ``axi_pkg`` -- the *implementation*. The numeric values the
  port_table width expressions elaborate to, the crossbar geometry and the AXI
  channel field widths come from there. A value taken from the implementation
  makes a compare against it a drift check on the elaborated design, not proof
  of a requirement, and the comment on each such constant says so.

This tree holds no SMU design specification for the crossbar topology, the AXI
channel geometry, the clock/reset domain table or the build configuration; the
SMU documentation directory contains ``port_table.adoc`` and nothing else. Where
a constant has no port_table row, that absence is stated rather than filled in
with another document.
"""

from __future__ import annotations

from typing import Any

from cocotb.triggers import Timer

# Ports port_table.adoc declares, at the widths it declares them. It gives
# those widths as parameter expressions (`[2*LC_STATE_WIDTH-1:0]`,
# `[XTRIG_NUM_CTP-1:0]`, `[Cfg.NUM_INT_TO_SMC-1:0]`, `[31:0]`); the numbers
# below are what those expressions elaborate to in hw/sys/smu/rtl/smu_pkg.sv
# and the dtp_pkg it imports, so a compare against one is a drift check on the
# elaborated parameter.
LC_STATE_O_WIDTH = 8
LCC_DEMOTE_WIDTH = 2
NUM_INT_TO_SMC = 256
XTRIG_NUM_CTP = 16
XTRIG_NUM_INT_CT = 8
XTRIG_SMC_INT_CT_LANES = 2
XTRIG_SMC_CLK_STOP_LANES = 1
XTRIG_NUM_CLK_STOP_REQ = 8
DTP_NUM_INT_CT = XTRIG_NUM_INT_CT + XTRIG_SMC_INT_CT_LANES
XTRIG_INT_CT_MODE_WIDTH = 32
NUM_SUBSYSTEMS = 32
SS_CONFIG_WIDTH = 32
SMN_IN_ID_WIDTH = 8
SMN_OUT_ID_WIDTH = 10
SUBSYS_IN_ID_WIDTH = 6
# port_table.adoc names the SMN boundary struct *types*
# (`smu_axi_xbar_pkg::axi_56_64_req_t`, `axi_out_req_t`) but not their field
# widths. These are the localparams those types are built from in
# hw/sys/smu/rtl/smu_axi_xbar_pkg.sv -- implementation, with no open
# specification to check them against.
XBAR_ADDR_WIDTH = 56
XBAR_DATA_WIDTH = 64
XBAR_USER_WIDTH = 12
SEP_SEC_DISABLE_TOKEN_WIDTH = 256
SEP_OTP_PL_DEPTH = 3

# AMBA AXI4 channel field widths as the vendored pulp-platform
# `AXI_TYPEDEF_*_CHAN_T` macros lay them out, including the 6-bit
# `axi_pkg::atop_t` the AW channel carries. Sources:
# vendor/pulp-platform/axi/upstream/include/axi/typedef.svh and
# vendor/pulp-platform/axi/upstream/src/axi_pkg.sv.
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


# smu_pkg::smu_cfg_t in declaration order, MSB first, with each field's width
# taken from its declared type in hw/sys/smu/rtl/smu_pkg.sv. This table and the
# defaults below mirror the package, so decoding an elaborated `Cfg` with it and
# comparing the fields detects unintended drift in the elaborated build
# parameters and nothing more: there is no SMU specification of this struct to
# check it against, and a compare of a `Cfg` field against this table cannot
# distinguish a correct design from an incorrect one.
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
    ("XTRIG_NUM_CTP", 32),
    ("XTRIG_NUM_INT_CT", 32),
    ("XTRIG_NUM_CLK_STOP_REQ", 32),
    ("XTRIG_INT_CT_MODE", XTRIG_INT_CT_MODE_WIDTH),
    ("SMC_OTP_RD_PL_DEPTH", 2),
    ("SMC_OTP_WR_PL_DEPTH", 2),
    ("SMC_RD_PL_DEPTH", 2),
    ("SMC_WR_PL_DEPTH", 2),
    ("SEP_KM_LATCHED_MEM_RDATA", 1),
    ("SEP_ABR_MASKING_EN", 1),
    ("SEP_ABR_SRAM_LATENCY", 32),
)
CFG_TOTAL_BITS = sum(width for _, width in CFG_LAYOUT)

# smu_pkg::DefaultCfg, field for field. XTRIG_INT_CT_MODE is omitted: the
# wrapper testbench elaborates it from +xtrig_int_ct_mode rather than taking the
# package default, so the leaf supplies that one expectation itself.
CFG_ELABORATION_DEFAULTS: dict[str, int] = {
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
    "XTRIG_NUM_CTP": XTRIG_NUM_CTP,
    "XTRIG_NUM_INT_CT": XTRIG_NUM_INT_CT,
    "XTRIG_NUM_CLK_STOP_REQ": XTRIG_NUM_CLK_STOP_REQ,
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
