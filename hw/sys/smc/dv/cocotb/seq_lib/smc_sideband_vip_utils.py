# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded sideband VIP helpers for SMC OSS tests."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

# PROVENANCE. The AVS FSM state encoding has no SPEC table: `avsbus_controller`'s
# architecture document (hw/ip/avsbus_controller/doc/architecture.adoc:249-277)
# names the protocol states but publishes no codes, and the RDL exports no
# state field -- `AVS_NORMAL_STATUS.AVS_BUS_IS_IDLE` is a separate one-bit
# status, not this bus. The one authoritative in-tree source is the `state_t`
# enum in the RTL, so the map is PARSED from it rather than transcribed into a
# literal here. A compare built on it therefore cannot detect a wrong encoding
# -- it moves with the RTL -- but it also cannot silently rot out of step with
# it, and the parse fails loudly if the enum is renamed or removed.
_AVSBUS_RTL = (
    Path(__file__).resolve().parents[6]
    / "hw"
    / "ip"
    / "avsbus_controller"
    / "rtl"
    / "avsbus_controller.sv"
)
_STATE_ENUM_RE = re.compile(r"typedef\s+enum\s+logic\s*\[16:0\]\s*\{(.*?)\}\s*state_t\s*;", re.S)
_STATE_ROW_RE = re.compile(r"(AVS_\w+)\s*=\s*17'b([01]{17})")


@lru_cache(maxsize=1)
def avs_state_map() -> dict[int, str]:
    """One-hot code -> state name, parsed from ``avsbus_controller.sv``'s state_t."""
    text = _AVSBUS_RTL.read_text(encoding="utf-8")
    body = _STATE_ENUM_RE.search(text)
    if body is None:
        raise RuntimeError(f"state_t enum not found in {_AVSBUS_RTL}")
    out = {int(bits, 2): name for name, bits in _STATE_ROW_RE.findall(body.group(1))}
    if not out:
        raise RuntimeError(f"no AVS_* state rows parsed from {_AVSBUS_RTL}")
    return out


AVS_STATE_IDLE = next(code for code, name in avs_state_map().items() if name == "AVS_IDLE")


async def check_sideband_observability() -> None:
    """Verify sideband IRQ/state observability remains known after CSR probes.

    Shared by ``octs_sanity_test``, ``smc_avsbus_sanity_test``,
    ``smc_avsbus_clock_config_proxy_test`` and ``smc_avsbus_status_depth_test``.

    ``is_resolvable`` asserts alone cannot carry this function. Verilator is a
    2-state simulator, so nothing is ever unresolvable there and such asserts
    are constant-true, leaving the four testcases that cite this as their
    sideband observability proof with nothing that can fail
    ([NO-ALWAYS-PASS-CHECKER]). The ``is_resolvable`` guards below are retained
    because they do carry weight on a 4-state run (VCS / Xcelium); the checks
    are the one-hot, quiescence and encoding compares that follow them.
    """
    dut = cocotb.top

    await ClockCycles(dut.clk_smc_i, 16)
    # 4-state-only guards. No-ops under Verilator; retained for VCS/Xcelium.
    assert dut.tb_avsbus_irq.value.is_resolvable, "AVSBus IRQ bit is not resolvable"
    assert dut.tb_telemetry_irq_any.value.is_resolvable, "Telemetry IRQ aggregate is not resolvable"
    assert dut.tb_avsbus_cur_state_debug.value.is_resolvable, (
        "AVSBus current-state debug is not resolvable"
    )

    avs_irq = int(dut.tb_avsbus_irq.value)
    tel_irq = int(dut.tb_telemetry_irq_any.value)
    state = int(dut.tb_avsbus_cur_state_debug.value)

    # (1) SPEC-LEVEL, provenance-clean: the debug bus is a one-hot encoded FSM
    # state. Exactly one bit must be set. This does not depend on knowing which
    # state the FSM is in, or on any encoding transcribed from RTL, so it is the
    # strongest claim available here: an FSM that decoded to no state or to two
    # states at once fails it.
    onehot_bits = bin(state).count("1")
    assert onehot_bits == 1, (
        f"AVSBus FSM state debug 0x{state:x} has {onehot_bits} bits set; a "
        f"one-hot encoded state must have exactly one"
    )

    # (2) Quiescence. None of the four callers configures or triggers an AVSBus
    # or telemetry interrupt before this point -- they issue CSR probes only --
    # so both aggregates must still be deasserted. A spuriously asserting IRQ
    # fails here instead of being logged and ignored.
    assert avs_irq == 0, (
        f"AVSBus IRQ asserted ({avs_irq}) after CSR probes that configure no interrupt source"
    )
    assert tel_irq == 0, (
        f"Telemetry IRQ aggregate asserted ({tel_irq}) after CSR probes that "
        f"configure no interrupt source"
    )

    # (3) The FSM must still be in IDLE. The encoding is RTL-sourced (see the
    # provenance note at `avs_state_map`), so this compare cannot detect a wrong
    # encoding. What it does detect is the FSM having left IDLE and not
    # returned, or having advanced as a side effect of a CSR probe that is not
    # supposed to launch a transaction. The sampled code is also required to be
    # a state the enum declares at all, which a decode to an undeclared one-hot
    # bit fails.
    states = avs_state_map()
    assert state in states, (
        f"AVSBus FSM state debug 0x{state:x} is not any code declared by "
        f"`state_t`: {sorted(hex(c) for c in states)}"
    )
    assert state == AVS_STATE_IDLE, (
        f"AVSBus FSM is in {states[state]} (0x{state:x}), expected AVS_IDLE "
        f"(0x{AVS_STATE_IDLE:x}) after CSR probes only"
    )

    cocotb.log.info(
        "CHK-SIDEBAND-OBSERVABILITY: avs_irq=%d telemetry_irq=%d "
        "avs_state=0x%x=%s (one-hot, %d bit set, 1 of %d codes declared by "
        "avsbus_controller.sv state_t) -- IRQ aggregates quiescent and FSM in "
        "IDLE; the is_resolvable guards above are 4-state-only and are no-ops "
        "on this Verilator run",
        avs_irq,
        tel_irq,
        state,
        states[state],
        onehot_bits,
        len(states),
    )


async def sample_avsbus_cur_state() -> int:
    """Return resolvable ``tb_avsbus_cur_state_debug`` (17-bit one-hot FSM)."""
    dut = cocotb.top
    assert dut.tb_avsbus_cur_state_debug.value.is_resolvable, (
        "AVSBus current-state debug is not resolvable"
    )
    return int(dut.tb_avsbus_cur_state_debug.value)


async def wait_avsbus_leave_idle(max_cycles: int = 4000) -> int:
    """Poll until AVS FSM leaves IDLE (0x8); return the first non-idle state.

    No pad BFM exists here; this proves the DUT AVS controller FSM
    actually advances after an AVS_CMD CSR write (not just CSR readability).
    """
    dut = cocotb.top
    for _ in range(max_cycles):
        state = await sample_avsbus_cur_state()
        if state != AVS_STATE_IDLE:
            cocotb.log.info("AVSBus FSM left IDLE: cur_state_debug=0x%x", state)
            return state
        await ClockCycles(dut.clk_smc_i, 1)
    state = await sample_avsbus_cur_state()
    raise AssertionError(
        f"AVSBus FSM stayed IDLE (0x{AVS_STATE_IDLE:x}) for {max_cycles} "
        f"cycles after AVS_CMD kick (last=0x{state:x})"
    )
