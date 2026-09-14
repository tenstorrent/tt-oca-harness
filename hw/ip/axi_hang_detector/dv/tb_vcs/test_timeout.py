# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Timeout-counter / snoop-datapath unit tests for axi_hang_detector.

These drive the snoop probes to create *real* outstanding transactions and the
config wires directly (the IP has no CSR of its own). They cover the cycle-exact
behaviour of the saturating stall counter -- threshold, the conditions that
reset it, the level interrupt, threshold reconfiguration, and reset -- which is
hard to reproduce in the SMC-level system test. The config/propagation/OR path
is covered there (smc_hang_detector_sanity); this suite covers only the datapath.

irq_o is a direct combinational LEVEL: it is high while the counter is saturated
at threshold (bus still hung) and drops when a completion (or !enable) resets it.
"""

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from helpers import (
    complete_read,
    configure,
    issue_read,
    issue_write,
    reset_dut,
    set_threshold,
    setup_dut,
)


async def wait_for_irq(dut, max_cycles: int):
    """Advance up to max_cycles; return the cycle irq_o first asserts, else None."""
    for i in range(1, max_cycles + 1):
        await RisingEdge(dut.clk_i)
        if int(dut.irq_o.value) == 1:
            return i
    return None


# Core datapath sanity, walked as one sequence: read hang, completion, write hang,
# reset. irq_o is a level, not a pulse: it holds while the bus stays hung. The
# precise corners (threshold edges, latching, periodic completions) live in the
# dedicated tests below.
@cocotb.test()
async def test_core_sanity(dut):
    THRESH = 32
    await setup_dut(dut)
    await configure(dut, THRESH)

    # 1. Read hang: must stay low until the threshold, then fire and hold high.
    await issue_read(dut)  # one outstanding read, never completed
    await ClockCycles(dut.clk_i, THRESH - 2)
    assert dut.irq_o.value == 0, "irq_o asserted too early (before threshold)"
    assert await wait_for_irq(dut, 16) is not None, "read hang never asserted irq_o"
    await ClockCycles(dut.clk_i, THRESH + 8)  # irq_o is a level: holds while hung
    assert dut.irq_o.value == 1, "irq_o should stay high while the bus remains hung (level)"

    # 2. Completing the read drains the outstanding tx -> irq_o drops.
    await complete_read(dut)
    await ClockCycles(dut.clk_i, 2)
    assert dut.irq_o.value == 0, "irq_o should drop once the read completes"

    # 3. Write hang: an outstanding write with no B response fires the same way.
    await issue_write(dut)
    assert await wait_for_irq(dut, THRESH + 16) is not None, "write hang did not assert irq_o"

    # 4. Reset while the (write) hang is in progress: irq_o drops and stays low.
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 4)
    assert dut.irq_o.value == 0, "reset should clear irq_o"
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 8)
    assert dut.irq_o.value == 0, "irq_o should remain low after reset (detector disabled)"


# Config-corner behaviours -- each pokes one config field to an edge value against
# a real hang and checks fire/no-fire (a reset re-inits between cases).
@cocotb.test()
async def test_config_corners(dut):
    await setup_dut(dut)

    # threshold = 0 disables the detector: no fire despite a real hang (firmware must use >= 1).
    await configure(dut, 0)
    await issue_read(dut)
    res = await wait_for_irq(dut, 64)
    assert res is None and dut.irq_o.value == 0, "threshold=0 unexpectedly fired"

    # threshold = 1: smallest useful value -> a single stalled cycle fires.
    await reset_dut(dut)
    await configure(dut, 1)
    await issue_read(dut)
    assert await wait_for_irq(dut, 16) is not None, "threshold=1 should fire after ~1 stalled cycle"

    # irq_en = 0: a real hang runs the counter but irq_o stays gated low.
    await reset_dut(dut)
    await configure(dut, 8, enable=True, irq_en=False)
    await issue_read(dut)
    res = await wait_for_irq(dut, 32)
    assert res is None and dut.irq_o.value == 0, "irq_en=0 should keep irq_o low"


# The down-counter LATCHES the threshold when a stall window starts, so
# reprogramming it mid-count has no effect until the next window. Verify a
# mid-window change is ignored (fires at the latched value, not the new one),
# and that the new threshold then takes effect on the next stall window.
@cocotb.test()
async def test_threshold_latched_per_window(dut):
    await setup_dut(dut)
    await configure(dut, 20)

    # Window 1: latched threshold = 20. Raise it mid-count -> must be IGNORED,
    # so it still fires near the latched 20 (within ~25 cycles), not extended to 40.
    await issue_read(dut)
    await ClockCycles(dut.clk_i, 8)  # counting down from 20
    await set_threshold(dut, 40)  # mid-window change -> no effect this window
    fired = await wait_for_irq(dut, 25)
    assert fired is not None, (
        "mid-window threshold change should be ignored (fire at latched value)"
    )

    # Window 2: a completion reloads the counter with the new threshold (40); a
    # fresh hang must now take the LONGER time -> not fired at 30 cycles (< 40),
    # fired thereafter.
    await complete_read(dut)
    await ClockCycles(dut.clk_i, 2)
    await issue_read(dut)
    await ClockCycles(dut.clk_i, 30)  # 30 < 40 -> still counting
    assert dut.irq_o.value == 0, "next window should use the newly-latched (larger) threshold"
    fired = await wait_for_irq(dut, 25)
    assert fired is not None, "should fire once the new threshold elapses"


# A bus that stays busy but keeps making progress must never time out: with a
# completion every (< threshold) cycles the stall counter is repeatedly reset.
@cocotb.test()
async def test_periodic_completions_never_fire(dut):
    THRESH = 32
    await setup_dut(dut)
    await configure(dut, THRESH)

    for _ in range(6):
        await issue_read(dut)
        await ClockCycles(dut.clk_i, THRESH - 8)
        await complete_read(dut)
        assert dut.irq_o.value == 0, "periodic completions should keep resetting the counter"
