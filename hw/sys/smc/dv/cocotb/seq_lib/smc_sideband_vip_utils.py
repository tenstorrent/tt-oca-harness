# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded sideband VIP helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

# From avsbus_controller.sv one-hot state_t (bit0=RESET ... bit3=IDLE).
AVS_STATE_IDLE = 0x8


async def check_sideband_observability() -> None:
    """Verify sideband IRQ/state observability remains known after CSR probes."""
    dut = cocotb.top

    await ClockCycles(dut.clk_smc_i, 16)
    assert dut.tb_avsbus_irq.value.is_resolvable, "AVSBus IRQ bit is not resolvable"
    assert dut.tb_telemetry_irq_any.value.is_resolvable, "Telemetry IRQ aggregate is not resolvable"
    assert dut.tb_avsbus_cur_state_debug.value.is_resolvable, (
        "AVSBus current-state debug is not resolvable"
    )
    cocotb.log.info(
        "Sideband bounded VIP observed avs_irq=%d telemetry_irq=%d avs_state=0x%x",
        int(dut.tb_avsbus_irq.value),
        int(dut.tb_telemetry_irq_any.value),
        int(dut.tb_avsbus_cur_state_debug.value),
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
