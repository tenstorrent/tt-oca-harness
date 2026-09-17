# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""System Timer OCTS synchronization across a two-to-one clock ratio.

Scenarios:

1. Slow secondary — the secondary clock runs at twice the primary period
   with PULSE_WIDTH 2; after the sync load the counters stay within the
   documented tolerance over random samples and the secondary never runs
   ahead by more than one credit.
2. Fast secondary — the secondary clock runs at half the primary period with
   PULSE_WIDTH 1; the counters still track, the secondary spends each
   credit early and its CREDIT_EXPIRED grows while the primary's stays
   zero; a write to CREDIT_EXPIRED restarts its accumulation from zero.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from system_timer_octs_base_test import (
    CREDIT_VAL,
    DEFAULT_CLK_PERIOD_NS,
    PRESET_PRIMARY,
    PRESET_SECONDARY,
    PRIMARY,
    REG,
    SECONDARY,
    ClockPair,
    SystemTimerOctsTb,
    random_seed,
)

TRACK_SAMPLES = 100
TRACK_TOLERANCE = 10


async def start_and_track(tb: SystemTimerOctsTb, what: str) -> None:
    dut = tb.dut
    await tb.start_primary()
    await with_timeout(RisingEdge(dut.sync_load), 200 * tb.clocks.primary_ns, "ns")
    await ClockCycles(dut.clk_primary, 200)
    status = await tb.read_u(SECONDARY, REG.SYSTEM_TIMER_OCTS_STATUS_reg_u, REG.STATUS_REG_ADDR)
    assert status.f.running == 1, f"{what}: secondary STATUS.RUNNING clear after the sync load"
    worst = 0
    for primary, secondary in await tb.sample_counts(TRACK_SAMPLES, 5, 30, random):
        diff = primary - secondary
        worst = max(worst, abs(diff))
        assert abs(diff) < TRACK_TOLERANCE, (
            f"{what}: primary 0x{primary:x} - secondary 0x{secondary:x} = {diff}"
        )
        assert diff >= -CREDIT_VAL, f"{what}: secondary ran ahead of the primary by {-diff}"
    tb.log.info(
        "%s: worst primary/secondary difference %d (tolerance %d)", what, worst, TRACK_TOLERANCE
    )


@cocotb.test()
async def system_timer_octs_clock_ratio_test(dut) -> None:
    tb = SystemTimerOctsTb(dut, name="system_timer_octs_clock_ratio_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: secondary clock at twice the primary period")
    tb.log.info("=" * 70)
    await tb.start(
        ClockPair(primary_ns=DEFAULT_CLK_PERIOD_NS, secondary_ns=2 * DEFAULT_CLK_PERIOD_NS)
    )
    await tb.configure(PRIMARY, preset=PRESET_PRIMARY, pulse_width=2)
    await tb.configure(SECONDARY, preset=PRESET_SECONDARY, pulse_width=2)
    await start_and_track(tb, "slow secondary")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: secondary clock at half the primary period")
    tb.log.info("=" * 70)
    await tb.reclock(
        ClockPair(primary_ns=2 * DEFAULT_CLK_PERIOD_NS, secondary_ns=DEFAULT_CLK_PERIOD_NS)
    )
    await tb.configure(PRIMARY, preset=PRESET_PRIMARY, pulse_width=1)
    await tb.configure(SECONDARY, preset=PRESET_SECONDARY, pulse_width=1)
    await start_and_track(tb, "fast secondary")

    expired_primary = await tb.read(PRIMARY, REG.CREDIT_EXPIRED_REG_ADDR)
    expired_secondary = await tb.read(SECONDARY, REG.CREDIT_EXPIRED_REG_ADDR)
    assert expired_primary == 0, (
        f"primary CREDIT_EXPIRED {expired_primary}, expected 0 in primary mode"
    )
    assert expired_secondary > 0, (
        "secondary CREDIT_EXPIRED stayed 0 although it spends each credit early"
    )
    tb.log.info(
        "fast secondary: CREDIT_EXPIRED primary %d, secondary %d",
        expired_primary,
        expired_secondary,
    )

    await tb.write(SECONDARY, REG.CREDIT_EXPIRED_REG_ADDR, 1)
    after_clear = await tb.read(SECONDARY, REG.CREDIT_EXPIRED_REG_ADDR)
    assert after_clear < expired_secondary, (
        f"secondary CREDIT_EXPIRED {after_clear} not reset below {expired_secondary}"
    )
    tb.log.info("secondary CREDIT_EXPIRED restarted at %d after the clearing write", after_clear)

    tb.log.info("system_timer_octs_clock_ratio_test PASSED (seed=%d)", seed)
