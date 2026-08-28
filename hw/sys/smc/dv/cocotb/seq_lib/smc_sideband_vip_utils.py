# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded sideband VIP helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

# From avsbus_controller.sv one-hot state_t (bit0=RESET ... bit3=IDLE).
AVS_STATE_IDLE = 0x8


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
        f"AVSBus IRQ asserted ({avs_irq}) after CSR probes that configure no "
        f"interrupt source"
    )
    assert tel_irq == 0, (
        f"Telemetry IRQ aggregate asserted ({tel_irq}) after CSR probes that "
        f"configure no interrupt source"
    )

    # (3) The FSM must still be in IDLE. NOTE ON PROVENANCE: AVS_STATE_IDLE is
    # transcribed from `avsbus_controller.sv`'s one-hot `state_t`, not from a
    # spec table, so this compare CANNOT detect a wrong encoding -- it would
    # move with the RTL. What it does detect is the FSM having left IDLE and not
    # returned, or having advanced as a side effect of a CSR probe that is not
    # supposed to launch a transaction.
    assert state == AVS_STATE_IDLE, (
        f"AVSBus FSM is in state 0x{state:x}, expected IDLE 0x{AVS_STATE_IDLE:x} "
        f"after CSR probes only (encoding is RTL-sourced; see comment)"
    )

    cocotb.log.info(
        "CHK-SIDEBAND-OBSERVABILITY: avs_irq=%d telemetry_irq=%d "
        "avs_state=0x%x (one-hot, %d bit set) -- IRQ aggregates quiescent and "
        "FSM in IDLE; the is_resolvable guards above are 4-state-only and are "
        "no-ops on this Verilator run",
        avs_irq, tel_irq, state, onehot_bits,
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

    U4-4 pad BFM is still deferred; this proves DUT AVS controller FSM
    actually advances after an AVS_CMD CSR write (not just CSR readability).
    """
    dut = cocotb.top
    for _ in range(max_cycles):
        state = await sample_avsbus_cur_state()
        if state != AVS_STATE_IDLE:
            cocotb.log.info(
                "AVSBus FSM left IDLE: cur_state_debug=0x%x", state
            )
            return state
        await ClockCycles(dut.clk_smc_i, 1)
    state = await sample_avsbus_cur_state()
    raise AssertionError(
        f"AVSBus FSM stayed IDLE (0x{AVS_STATE_IDLE:x}) for {max_cycles} "
        f"cycles after AVS_CMD kick (last=0x{state:x})"
    )
