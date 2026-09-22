# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI Hang Detector threshold latch, per stall window.

The down-counter latches the threshold when a stall window starts, so
reprogramming it mid-count has no effect until the next window. A mid-window
change is ignored (the detector fires at the latched value, not the new one),
and the new threshold then takes effect on the next stall window.
"""

from __future__ import annotations

import cocotb
from ahd_base_test import (
    complete_read,
    configure,
    issue_read,
    set_threshold,
    setup_dut,
    wait_for_irq,
)
from cocotb.triggers import ClockCycles


@cocotb.test()
async def ahd_threshold_latch_test(dut) -> None:
    await setup_dut(dut)
    await configure(dut, 20)

    # Window 1: latched threshold = 20. Raise it mid-count -> must be IGNORED,
    # so it still fires near the latched 20 (within ~25 cycles), not extended to 40.
    await issue_read(dut)
    await ClockCycles(dut.clk, 8)  # counting down from 20
    await set_threshold(dut, 40)  # mid-window change -> no effect this window
    fired = await wait_for_irq(dut, 25)
    assert fired is not None, (
        "mid-window threshold change should be ignored (fire at latched value)"
    )

    # Window 2: a completion reloads the counter with the new threshold (40); a
    # fresh hang must now take the LONGER time -> not fired at 30 cycles (< 40),
    # fired thereafter.
    await complete_read(dut)
    await ClockCycles(dut.clk, 2)
    await issue_read(dut)
    await ClockCycles(dut.clk, 30)  # 30 < 40 -> still counting
    assert dut.irq_o.value == 0, "next window should use the newly-latched (larger) threshold"
    fired = await wait_for_irq(dut, 25)
    assert fired is not None, "should fire once the new threshold elapses"
