# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI Hang Detector re-arm out of threshold = 0.

threshold = 0 parks the counter at 0 with nothing to count, so the fired
condition comes from the armed latch rather than the counter value: a threshold
written over a 0 takes effect on the next window, not the stall in progress.
``irq_test`` is a separate path and stays live while detection is off.
"""

from __future__ import annotations

import cocotb
from ahd_base_test import (
    complete_read,
    configure,
    issue_read,
    set_irq_test,
    set_threshold,
    setup_dut,
    wait_for_irq,
)
from cocotb.triggers import ClockCycles


@cocotb.test()
async def ahd_threshold_zero_rearm_test(dut) -> None:
    await setup_dut(dut)
    await configure(dut, 0)

    # irq_test still reaches irq_o with detection disabled (enable & irq_en gate it).
    await set_irq_test(dut, 1)
    await ClockCycles(dut.clk, 2)
    assert dut.irq_o.value == 1, "irq_test should assert irq_o with threshold=0"
    await set_irq_test(dut, 0)
    await ClockCycles(dut.clk, 2)
    assert dut.irq_o.value == 0, "irq_o should drop when irq_test clears"

    # Raise the threshold with a stall already outstanding -> no fire this window.
    await issue_read(dut)
    await ClockCycles(dut.clk, 8)
    await set_threshold(dut, 16)
    res = await wait_for_irq(dut, 64)
    assert res is None and dut.irq_o.value == 0, (
        "threshold raised over 0 mid-stall should not fire until the next window"
    )

    # Next window: the completion re-arms at the new threshold, so a fresh hang fires.
    await complete_read(dut)
    await ClockCycles(dut.clk, 2)
    await issue_read(dut)
    assert await wait_for_irq(dut, 48) is not None, "next window should arm at the new threshold"
