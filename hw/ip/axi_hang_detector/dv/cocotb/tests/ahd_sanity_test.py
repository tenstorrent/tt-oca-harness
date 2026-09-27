# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI Hang Detector core datapath sanity, walked as one sequence.

Read hang, completion, write hang, reset. ``irq_o`` is a direct combinational
LEVEL: high while the counter is saturated at threshold (bus still hung),
dropping when a completion (or ``!enable``) resets it. The precise corners
(threshold edges, latching, periodic completions) live in the sibling tests.
"""

from __future__ import annotations

import cocotb
from ahd_base_test import (
    complete_read,
    configure,
    issue_read,
    issue_write,
    setup_dut,
    wait_for_irq,
)
from cocotb.triggers import ClockCycles


@cocotb.test()
async def ahd_sanity_test(dut) -> None:
    THRESH = 32
    await setup_dut(dut)
    await configure(dut, THRESH)

    # 1. Read hang: must stay low until the threshold, then fire and hold high.
    await issue_read(dut)  # one outstanding read, never completed
    await ClockCycles(dut.clk, THRESH - 2)
    assert dut.irq_o.value == 0, "irq_o asserted too early (before threshold)"
    assert await wait_for_irq(dut, 16) is not None, "read hang never asserted irq_o"
    await ClockCycles(dut.clk, THRESH + 8)  # irq_o is a level: holds while hung
    assert dut.irq_o.value == 1, "irq_o should stay high while the bus remains hung (level)"

    # 2. Completing the read drains the outstanding tx -> irq_o drops.
    await complete_read(dut)
    await ClockCycles(dut.clk, 2)
    assert dut.irq_o.value == 0, "irq_o should drop once the read completes"

    # 3. Write hang: an outstanding write with no B response fires the same way.
    await issue_write(dut)
    assert await wait_for_irq(dut, THRESH + 16) is not None, "write hang did not assert irq_o"

    # 4. Reset while the (write) hang is in progress: irq_o drops and stays low.
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 4)
    assert dut.irq_o.value == 0, "reset should clear irq_o"
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 8)
    assert dut.irq_o.value == 0, "irq_o should remain low after reset (detector disabled)"
