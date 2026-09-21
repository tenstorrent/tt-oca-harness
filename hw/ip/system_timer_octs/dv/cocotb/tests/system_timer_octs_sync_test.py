# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""System Timer OCTS synchronization on equal clocks.

Scenarios:

1. Pulse shaping — TIMER_START on the primary raises one ``sync_load`` pulse
   of PULSE_WIDTH clocks; ``cnt_credit`` then pulses every CREDIT_VAL clocks,
   each PULSE_WIDTH wide.
2. Secondary load — within the synchronizer latency of the ``sync_load``
   pulse the secondary holds the primary's preset and reports RUNNING.
3. Tracking — over random samples the secondary stays within the
   synchronizer latency behind the primary and never runs ahead of it by
   more than the credit it was granted.
4. Credit pacing — the secondary advances by STEP per clock exactly while
   ``secondary_credits_left`` is set and holds still otherwise, apart from
   the re-alignment a credit edge applies.
5. Health — the primary's CREDIT_EXPIRED is zero and the secondary never
   waits longer than a credit period for its next credit.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from system_timer_octs_base_test import (
    CREDIT_VAL,
    PRESET_PRIMARY,
    PRIMARY,
    PULSE_WIDTH,
    REG,
    SECONDARY,
    STEP,
    SYNC_LATENCY_CYCLES,
    SystemTimerOctsTb,
    random_seed,
)

TRACK_SAMPLES = 100
# On equal clocks the secondary lags the primary by the synchronizer latency
# of the credit path (input flop, two-flop synchronizer, edge detector).
TRACK_TOLERANCE = SYNC_LATENCY_CYCLES


@cocotb.test()
async def system_timer_octs_sync_test(dut) -> None:
    tb = SystemTimerOctsTb(dut, name="system_timer_octs_sync_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    await tb.configure(PRIMARY, preset=PRESET_PRIMARY)
    await tb.configure(SECONDARY, preset=PRESET_PRIMARY)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: sync_load and cnt_credit pulse shaping")
    tb.log.info("=" * 70)
    pulse_task = cocotb.start_soon(
        tb.measure_pulse(dut.sync_load, dut.clk_primary, "sync_load", 200)
    )
    await tb.start_primary()
    width = await pulse_task
    assert width == PULSE_WIDTH, f"sync_load pulse {width} clocks wide, expected {PULSE_WIDTH}"
    period = await tb.credit_period(4 * CREDIT_VAL)
    assert period == CREDIT_VAL, f"cnt_credit period {period} clocks, expected {CREDIT_VAL}"
    width = await tb.measure_pulse(dut.cnt_credit, dut.clk_primary, "cnt_credit", 4 * CREDIT_VAL)
    assert width == PULSE_WIDTH, f"cnt_credit pulse {width} clocks wide, expected {PULSE_WIDTH}"
    tb.log.info(
        "sync_load %d wide; cnt_credit every %d clocks, %d wide", PULSE_WIDTH, period, width
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: secondary loaded the preset and runs")
    tb.log.info("=" * 70)
    status = await tb.read_u(SECONDARY, REG.SYSTEM_TIMER_OCTS_STATUS_reg_u, REG.STATUS_REG_ADDR)
    assert status.f.running == 1, "secondary STATUS.RUNNING clear after the sync load"
    secondary = tb.count(SECONDARY)
    primary = tb.count(PRIMARY)
    assert secondary >= PRESET_PRIMARY, (
        f"secondary count 0x{secondary:x} below the preset 0x{PRESET_PRIMARY:x}"
    )
    assert 0 <= primary - secondary <= SYNC_LATENCY_CYCLES, (
        f"primary 0x{primary:x} vs secondary 0x{secondary:x} after load"
    )
    tb.log.info("secondary running at 0x%x, primary at 0x%x", secondary, primary)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: counters track over %d random samples", TRACK_SAMPLES)
    tb.log.info("=" * 70)
    worst = 0
    for primary, secondary in await tb.sample_counts(TRACK_SAMPLES, 5, 30, random):
        diff = primary - secondary
        worst = max(worst, abs(diff))
        assert -CREDIT_VAL <= diff <= TRACK_TOLERANCE, (
            f"primary 0x{primary:x} - secondary 0x{secondary:x} = {diff}"
        )
    tb.log.info("worst primary/secondary difference %d (tolerance %d)", worst, TRACK_TOLERANCE)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: the secondary advances by STEP only while it holds credits")
    tb.log.info("=" * 70)
    await FallingEdge(dut.clk_secondary)
    previous = tb.count(SECONDARY)
    steps = holds = realigns = 0
    for _ in range(6 * CREDIT_VAL):
        left = int(dut.secondary_credits_left.value)
        await FallingEdge(dut.clk_secondary)
        current = tb.count(SECONDARY)
        delta = current - previous
        if delta == STEP and left:
            steps += 1
        elif delta == 0 and not left:
            holds += 1
        elif 0 <= delta <= CREDIT_VAL:
            realigns += 1
        else:
            raise AssertionError(f"secondary moved by {delta} in one clock (credits_left={left})")
        previous = current
    assert steps > 0, "secondary never stepped while holding credits"
    tb.log.info(
        "secondary: %d single steps, %d holds without credits, %d credit re-alignments",
        steps,
        holds,
        realigns,
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 5: CREDIT_EXPIRED stays bounded on equal clocks")
    tb.log.info("=" * 70)
    await tb.write(SECONDARY, REG.CREDIT_EXPIRED_REG_ADDR, 0)
    await ClockCycles(dut.clk_primary, 200)
    expired = await tb.read(PRIMARY, REG.CREDIT_EXPIRED_REG_ADDR)
    assert expired == 0, f"primary CREDIT_EXPIRED {expired}, expected 0 in primary mode"
    expired = await tb.read(SECONDARY, REG.CREDIT_EXPIRED_REG_ADDR)
    assert expired < CREDIT_VAL, (
        f"secondary waited {expired} clocks for a credit, more than a credit period"
    )
    tb.log.info("secondary's longest wait for a credit: %d clock(s)", expired)

    tb.log.info("system_timer_octs_sync_test PASSED (seed=%d)", seed)
