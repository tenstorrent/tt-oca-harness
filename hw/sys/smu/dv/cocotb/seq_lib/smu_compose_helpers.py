# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helpers shared by the SMU composition and bring-up sequences.

The expected values the composition leaves compare against live here, each
with the specification it is transcribed from: ``doc/integrator/src/smu.adoc``
and ``doc/integrator/src/smu-smc.adoc``, the SMU, SMC, SEP and DTP port
tables, the SMC interrupt and fabric documents, the SEP security-disable
document, or a generated register header. A value no specification in this
tree states is not compared: the SMN crossbar's transaction-ID and user
widths, the SEP inbound ID width, the packed layout of the crossbar's channel
structs and the packed layout of the SMU build-configuration struct are read
from the elaboration alone, and a compare against a recorded elaboration
proves no requirement.

The sections the cites name: "SMU Default Parameters", "Cross Trigger
Parameters", "JTAG Configuration Parameters", "Pipeline Depth Parameters" and
"Debug & Test Ports (DTP) Integration" in ``doc/integrator/src/smu.adoc``;
"AXI Interface Configuration" in ``doc/integrator/src/smu-smc.adoc``; the
"SMU Port Declaration" table in ``hw/sys/smu/doc/port_table.adoc``.
"""

from __future__ import annotations

from typing import Any

from cocotb.triggers import Timer

# doc/integrator/src/smu.adoc "SMU Default Parameters" and "Cross Trigger
# Parameters": 16 external CTPs, 8 SMU-exposed internal CT lanes and 8
# SMU-exposed clock-stop requests; the low XTRIG_NUM_INT_CT bits of the mode
# vector are the ones consumed.
XTRIG_NUM_CTP = 16
XTRIG_NUM_INT_CT = 8
XTRIG_NUM_CLK_STOP_REQ = 8
# doc/integrator/src/smu.adoc "Debug & Test Ports (DTP) Integration": the DTP
# carries 10 internal CTs and 9 clock-stop requests, 8 and 8 of them exposed;
# the lanes below the exposed ones are the SMC reservation, held in pulse-sync
# mode with their mode bits at zero.
XTRIG_SMC_INT_CT_LANES = 2
XTRIG_SMC_CLK_STOP_LANES = 1
DTP_NUM_INT_CT = XTRIG_NUM_INT_CT + XTRIG_SMC_INT_CT_LANES
DTP_NUM_CLK_STOP_REQ = XTRIG_NUM_CLK_STOP_REQ + XTRIG_SMC_CLK_STOP_LANES
# hw/sys/smc/doc/port_table.adoc `smc_ext_interrupts_i` ("Width is 256") and
# hw/sys/smc/doc/interrupts.adoc (`NumExtInterrupts = 256`): the SMC port that
# the SMU `smc_ext_interrupts_i` row (`[CFG.NUM_INT_TO_SMC-1:0]`) feeds.
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
# doc/integrator/src/smu-smc.adoc "AXI Interface Configuration" (`sys_axi_in`
# "uses a 56-bit address space with 64-bit data width and 6-bit transaction
# IDs") and hw/sys/smc/doc/port_table.adoc `sys_axi_in_req_i`: the SMC system
# AXI input, the port the crossbar's SMC leg lands on.
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


async def count_transitions(signals: dict[str, Any], window_ns: int, step_ps: int = 250) -> dict:
    """Count level changes on each signal over ``window_ns`` at ``step_ps`` resolution.

    The step has to be shorter than half the shortest period counted; the
    800 MHz sys clock has a 625 ps half period.
    """
    last = {name: sample(sig, name) for name, sig in signals.items()}
    counts = {name: 0 for name in signals}
    for _ in range(window_ns * 1000 // step_ps):
        await Timer(step_ps, unit="ps")
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
