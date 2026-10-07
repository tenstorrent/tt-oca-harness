# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded sideband VIP helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

# --- AVSBus protocol FSM as seen on `avsbus_cur_state_debug` ----------------
# hw/ip/avsbus_controller/doc/architecture.adoc "Protocol State Machine" names
# the protocol states and defines IDLE as waiting for commands from software;
# hw/ip/avsbus_controller/doc/interface.adoc defines the idle bus: avs_mdata_o
# held high between transactions. Neither the spec nor the RDL publishes the
# state encoding (`AVS_NORMAL_STATUS.AVS_BUS_IS_IDLE` is a separate status
# bit, not this bus), so the values below are DV-owned goldens, not a
# transcription: the debug bus is one-hot, and IDLE is the code this bench
# expects from a quiescent controller. `check_sideband_observability` proves
# the golden in the same sample it uses it -- the code must coincide with the
# spec's idle bus -- so a wrong table fails the run instead of moving with the
# design.
AVS_STATE_IDLE = 1 << 3
# Consecutive clk_smc_i samples over which the spec's idle-bus condition
# (avs_mdata_o high) must hold alongside the IDLE code.
AVS_IDLE_BUS_SAMPLES = 16


def _avs_mdata_high() -> bool:
    """Spec idle-bus observable: ``avs_mdata_o`` (pad AVS.MDATA) resolves to 1."""
    sig = cocotb.top.tb_avs_mdata_from_dut.value
    return sig.is_resolvable and int(sig) == 1


async def check_sideband_observability() -> None:
    """Verify sideband IRQ/state observability remains known after CSR probes.

    ``is_resolvable`` asserts are constant-true under Verilator (a 2-state
    simulator) and carry weight only on a 4-state run (VCS / Xcelium); the
    fail-capable checks are the one-hot, quiescence and encoding compares that
    follow them ([NO-ALWAYS-PASS-CHECKER]).
    """
    dut = cocotb.top

    # Positive control for the DV-owned IDLE code: over the settle window the
    # bus must show the spec's idle state (mdata held high) on every sample.
    # A code labelled IDLE while the bus is mid-frame fails here, not silently.
    mdata_high_samples = 0
    for _ in range(AVS_IDLE_BUS_SAMPLES):
        await ClockCycles(dut.clk_smc_i, 1)
        mdata_high_samples += int(_avs_mdata_high())
    assert mdata_high_samples == AVS_IDLE_BUS_SAMPLES, (
        f"avs_mdata_o was high on {mdata_high_samples}/{AVS_IDLE_BUS_SAMPLES} samples; the "
        "spec idle bus holds mdata high between transactions, so the controller is not idle"
    )
    # 4-state-only guards: constant-true under Verilator, fail-capable on VCS/Xcelium.
    assert dut.tb_avsbus_irq.value.is_resolvable, "AVSBus IRQ bit is not resolvable"
    assert dut.tb_telemetry_irq_any.value.is_resolvable, "Telemetry IRQ aggregate is not resolvable"
    assert dut.tb_avsbus_cur_state_debug.value.is_resolvable, (
        "AVSBus current-state debug is not resolvable"
    )

    avs_irq = int(dut.tb_avsbus_irq.value)
    tel_irq = int(dut.tb_telemetry_irq_any.value)
    state = int(dut.tb_avsbus_cur_state_debug.value)

    # (1) The debug bus is a one-hot encoded FSM state: exactly one bit set.
    # This does not depend on knowing which state the FSM is in, so an FSM
    # that decoded to no state or to two states at once fails it whatever the
    # encoding.
    onehot_bits = bin(state).count("1")
    assert onehot_bits == 1, (
        f"AVSBus FSM state debug 0x{state:x} has {onehot_bits} bits set; a "
        f"one-hot encoded state must have exactly one"
    )

    # (2) Quiescence. No caller configures or triggers an AVSBus or telemetry
    # interrupt before this point -- callers issue CSR probes only --
    # so both aggregates must still be deasserted. A spuriously asserting IRQ
    # fails here instead of being logged and ignored.
    assert avs_irq == 0, (
        f"AVSBus IRQ asserted ({avs_irq}) after CSR probes that configure no interrupt source"
    )
    assert tel_irq == 0, (
        f"Telemetry IRQ aggregate asserted ({tel_irq}) after CSR probes that "
        f"configure no interrupt source"
    )

    # (3) The FSM must still be in IDLE. The IDLE code is the DV-owned golden
    # above; the idle-bus samples taken before this read are what make it a
    # measurement rather than an agreement with the design.
    assert state == AVS_STATE_IDLE, (
        f"AVSBus FSM debug state 0x{state:x}, expected AVS_IDLE (0x{AVS_STATE_IDLE:x}) "
        "after CSR probes only"
    )

    cocotb.log.info(
        "CHK-SIDEBAND-OBSERVABILITY: avs_irq=%d telemetry_irq=%d "
        "avs_state=0x%x=AVS_IDLE (one-hot; avs_mdata_o high on %d/%d samples) "
        "-- IRQ aggregates quiescent and FSM in IDLE; the "
        "is_resolvable guards above are 4-state-only and are no-ops on this "
        "Verilator run",
        avs_irq,
        tel_irq,
        state,
        mdata_high_samples,
        AVS_IDLE_BUS_SAMPLES,
    )


async def sample_avsbus_cur_state() -> int:
    """Return resolvable ``tb_avsbus_cur_state_debug`` (one-hot FSM state)."""
    dut = cocotb.top
    assert dut.tb_avsbus_cur_state_debug.value.is_resolvable, (
        "AVSBus current-state debug is not resolvable"
    )
    return int(dut.tb_avsbus_cur_state_debug.value)


async def wait_avsbus_leave_idle(max_cycles: int = 4000) -> int:
    """Poll until the AVS FSM leaves ``AVS_STATE_IDLE``; return the first non-idle state.

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
