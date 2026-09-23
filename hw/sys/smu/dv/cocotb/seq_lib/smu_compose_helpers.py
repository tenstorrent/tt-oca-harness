# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helpers shared by the SMU composition and bring-up sequences.

The expected values the composition leaves compare against live here, each
with the specification it is transcribed from. Two kinds of constant appear
below and they do not carry the same weight:

* A constant with a specification cite -- ``doc/integrator/src/smu.adoc``,
  the SMU, SMC, SEP and DTP port tables, the SMC interrupt and fabric
  documents, the SEP security-disable document, or a generated register
  header -- is a golden. A compare against it may carry an evidence token.
* A constant in the drift tables has no specification in this tree. It
  records what the boundary elaborated to when it was recorded, so a compare
  against it detects unintended change and proves no requirement. No compare
  built on a drift constant carries an evidence token, and the plan cards say
  which compares those are.

The sections the cites name: "SMU Default Parameters", "Cross Trigger
Parameters", "JTAG Configuration Parameters", "Pipeline Depth Parameters",
"AXI Interface Configuration" and "Debug & Test Ports (DTP) Integration" in
``doc/integrator/src/smu.adoc``; the "SMU Port Declaration" table in
``hw/sys/smu/doc/port_table.adoc``.
"""

from __future__ import annotations

from typing import Any

from cocotb.triggers import Timer

# doc/integrator/src/smu.adoc "SMU Default Parameters" and "Cross Trigger
# Parameters": 16 external CTPs, 8 SMU-exposed internal CT lanes, 8 SMU-exposed
# clock-stop requests, and a 32-bit mode vector of which the low
# XTRIG_NUM_INT_CT bits are consumed.
XTRIG_NUM_CTP = 16
XTRIG_NUM_INT_CT = 8
XTRIG_NUM_CLK_STOP_REQ = 8
XTRIG_INT_CT_MODE_WIDTH = 32
# doc/integrator/src/smu.adoc "Debug & Test Ports (DTP) Integration": the DTP
# carries 10 internal CTs and 9 clock-stop requests, 8 and 8 of them exposed;
# the lanes below the exposed ones are the SMC reservation, held in pulse-sync
# mode with their mode bits at zero.
XTRIG_SMC_INT_CT_LANES = 2
XTRIG_SMC_CLK_STOP_LANES = 1
DTP_NUM_INT_CT = XTRIG_NUM_INT_CT + XTRIG_SMC_INT_CT_LANES
DTP_NUM_CLK_STOP_REQ = XTRIG_NUM_CLK_STOP_REQ + XTRIG_SMC_CLK_STOP_LANES
# hw/sys/smc/doc/port_table.adoc `smc_ext_interrupts_i` ("Width is 256") and
# hw/sys/smc/doc/interrupts.adoc (`NUM_EXT_INTERRUPTS = 256`): the SMC port that
# the SMU `smc_ext_interrupts_i` row (`[Cfg.NUM_INT_TO_SMC-1:0]`) feeds.
NUM_INT_TO_SMC = 256
# hw/sys/smu/doc/port_table.adoc `lc_state_o` (`[2*LC_STATE_WIDTH-1:0]`, tie
# value `8'hf0`); hw/sys/smc/doc/port_table.adoc `lc_state_i` "(8 bits)";
# hw/sys/sep/doc/otp_fuse_controller.adoc gives the life-cycle state width as 4.
LC_STATE_O_WIDTH = 8
# hw/sys/smu/doc/port_table.adoc `lcc_demote_state_1_o` / `_2_o`: `[1:0]`.
LCC_DEMOTE_WIDTH = 2
# hw/sys/smu/doc/port_table.adoc `ss_reset_ctrl_o` and `isolate_req_o`: 32
# subsystems.
NUM_SUBSYSTEMS = 32
# doc/integrator/src/smu.adoc "AXI Interface Configuration" and
# hw/sys/smc/doc/port_table.adoc `sys_axi_in_req_i`: 6-bit transaction IDs on
# the SMC system AXI input, the port the crossbar's SMC leg lands on.
SMC_SYS_IN_ID_WIDTH = 6
# hw/sys/sep/doc/security_disable.adoc: the security-disable token is a
# 256-bit value.
SEP_SEC_DISABLE_TOKEN_WIDTH = 256
# doc/integrator/src/smu.adoc "Pipeline Depth Parameters": the SEP OTP depths
# are fixed to 2'h3 in the SMU; the SMC OTP depths default to 2'h3 and pass
# through to the DTP.
SEP_OTP_PL_DEPTH = 3
SMC_OTP_PL_DEPTH = 3
# doc/integrator/src/smu.adoc "JTAG Configuration Parameters": one extra STAP,
# and the extra-STAP port arrays are as wide as the parameter.
JTAG_NUM_EXTRA_STAPS = 1

# Drift table: no specification in this tree states the SMN crossbar's
# transaction-ID widths, the user sideband it carries, the SEP inbound ID
# width, or the packed layout of the crossbar's channel structs. The address
# and data widths match the `axi_56_64_req_t` type name port_table.adoc gives
# the SMN inbound port; the rest is the recorded elaboration.
XBAR_ADDR_WIDTH = 56
XBAR_DATA_WIDTH = 64
XBAR_USER_WIDTH = 12
SMN_IN_ID_WIDTH = 8
SMN_OUT_ID_WIDTH = 10
SEP_IN_ID_WIDTH = 6

# AMBA AXI4 channel field widths: AxLEN, AxSIZE, AxBURST, AxLOCK, AxCACHE,
# AxPROT, AxQOS, AxREGION, xRESP, xLAST. The 6-bit atomic-operation field on
# the AW channel and the per-channel valid/ready and user bits are part of the
# drift table above.
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
    """Packed width of a crossbar request struct for one ID width (drift table)."""
    aw = id_width + _AXI_AX_COMMON + _AXI_ATOP
    w = XBAR_DATA_WIDTH + XBAR_DATA_WIDTH // 8 + _AXI_LAST + XBAR_USER_WIDTH
    ar = id_width + _AXI_AX_COMMON
    return aw + 1 + w + 1 + 1 + ar + 1 + 1


def axi_resp_bits(id_width: int) -> int:
    """Packed width of a crossbar response struct for one ID width (drift table)."""
    b = id_width + _AXI_RESP + XBAR_USER_WIDTH
    r = id_width + XBAR_DATA_WIDTH + _AXI_RESP + _AXI_LAST + XBAR_USER_WIDTH
    return 1 + 1 + 1 + 1 + b + 1 + r


# Drift table: no specification in this tree states the packed field order or
# the field widths of the SMU build-configuration struct. Decoding an
# elaborated `Cfg` with this layout and comparing the fields detects unintended
# change in the elaborated build parameters and proves no requirement; no
# compare that goes through `decode_cfg` carries an evidence token.
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

# doc/integrator/src/smu.adoc "SMU Default Parameters", field for field, with
# NUM_INT_TO_SMC from the SMC port it sizes. XTRIG_INT_CT_MODE is absent
# because the wrapper testbench elaborates it from +xtrig_int_ct_mode and the
# leaf supplies that expectation; SEP_KM_LATCHED_MEM_RDATA is absent because
# no specification states its default, so it is decoded and logged, not
# compared.
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
    "JTAG_NUM_EXTRA_STAPS": JTAG_NUM_EXTRA_STAPS,
    "JTAG_IDCODE_MFR_ID": 0,
    "JTAG_IDCODE_PART_NUM": 0,
    "JTAG_IDCODE_SI_REV": 0,
    "JTAG_OCH_VER": 0,
    "XTRIG_NUM_CTP": XTRIG_NUM_CTP,
    "XTRIG_NUM_INT_CT": XTRIG_NUM_INT_CT,
    "XTRIG_NUM_CLK_STOP_REQ": XTRIG_NUM_CLK_STOP_REQ,
    "SMC_OTP_RD_PL_DEPTH": SMC_OTP_PL_DEPTH,
    "SMC_OTP_WR_PL_DEPTH": SMC_OTP_PL_DEPTH,
    "SMC_RD_PL_DEPTH": 3,
    "SMC_WR_PL_DEPTH": 3,
    "SEP_ABR_MASKING_EN": 1,
    "SEP_ABR_SRAM_LATENCY": 1,
}


def decode_cfg(raw: int) -> dict[str, int]:
    """Split an elaborated build-configuration value into its named fields."""
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


def _lookup(node: Any, name: str) -> Any:
    try:
        return getattr(node, name)
    except Exception:  # noqa: BLE001 - the handle's exception type varies
        return None


def hier(root: Any, path: str) -> Any:
    """Resolve a dotted hierarchical path, naming the first missing element.

    Verilator exposes a generate block as a handle of its own; VCS folds the
    block name into its children, so `gen_sep.u_sep` is one child named
    `gen_sep.u_sep`. A part that does not resolve is therefore joined with the
    parts after it before the path is declared missing.
    """
    node = root
    walked: list[str] = []
    pending: list[str] = []
    for part in path.split("."):
        pending.append(part)
        found = _lookup(node, ".".join(pending))
        if found is None:
            continue
        walked.append(".".join(pending))
        pending = []
        node = found
    if pending:
        raise AssertionError(f"hierarchy element {'.'.join(walked + pending)} not found")
    return node


class GenerateScope:
    """A named generate block under ``parent`` on either simulator.

    ``exists()`` is true when the block was elaborated, ``has(child)`` when an
    instance of that name sits inside it, and ``get(child)`` returns the
    instance handle; each reads the block as a handle where the simulator
    offers one and through the folded ``block.child`` names where it does not.
    """

    def __init__(self, parent: Any, name: str) -> None:
        self._parent = parent
        self._name = name
        self._handle = _lookup(parent, name)

    def _folded(self) -> set[str]:
        try:
            self._parent._discover_all()
            names = set(self._parent._sub_handles)
        except Exception:  # noqa: BLE001 - not a hierarchy handle
            return set()
        prefix = f"{self._name}."
        return {n[len(prefix) :] for n in names if n.startswith(prefix)}

    def exists(self) -> bool:
        return self._handle is not None or bool(self._folded())

    def has(self, child: str) -> bool:
        if self._handle is not None:
            return _lookup(self._handle, child) is not None
        return child in self._folded()

    def get(self, child: str) -> Any:
        node = None if self._handle is None else _lookup(self._handle, child)
        if node is None:
            node = _lookup(self._parent, f"{self._name}.{child}")
        if node is None:
            raise AssertionError(f"hierarchy element {self._name}.{child} not found")
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
