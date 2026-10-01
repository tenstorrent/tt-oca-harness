# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Port on a shared open-drain wire with several drivers.

Scenarios:

1. Reset on the shared wire — a wire resting at its pull through reset
   produces no trigger; a wire held asserted through reset produces none on
   reset release and none when it is released afterwards, and the next
   assertion produces exactly one; a pull-down board brought up by writing
   INVERT=1 produces no trigger for the write and one for the first pull.
2. INVERT written against the board — INVERT=1 written while the wire rests
   high moves the sensed wire from rest to asserted and yields one trigger;
   writing INVERT=0 back yields none.
3. Two external chiplets — overlapping, staggered, adjacent, one-cycle-gap
   and separate pulls, directed then seeded; the port delivers one trigger
   per continuous wire assertion, never one per driver.
4. The port among the chiplets — its own stretched pull merges with an
   external pull into one trigger, a pull that starts while the port is
   already pulling is absorbed, a pull in the cycle the port releases keeps
   the wire asserted, and a pull one cycle after the release is a second
   trigger; the port's own pulls alone are one trigger each.
5. Model self-check — INVERT=1 on a pull-up board leaves the port unable to
   move the wire: the bench flags the pull mismatch for the stretched window
   and no trigger occurs.

Every scenario compares the ct_dst pulses against the wire-OR receive model
in ctp_base_test cycle for cycle, and states the number of wire assertions it
produced so the model cannot pass on silence.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from ctp_base_test import (
    CtpTb,
    random_seed,
)

# Seeded iterations of the two-chiplet and port-among-chiplets sweeps.
N_RAND_ITER = 16

# Two-chiplet pull patterns and the number of wire assertions each produces.
TWO_DRIVER_PATTERNS = {
    "simultaneous": 1,
    "staggered": 1,
    "adjacent": 1,
    "gap_one": 2,
    "separate": 2,
}

# Idle cycles the port-among-chiplets sweep leaves between the stretched
# window and the next stimulus, beyond the receive settle time.
WINDOW_TAIL_CYCLES = 4


async def _hold(tb: CtpTb, cycles: int) -> None:
    """Advance ``cycles`` clocks; zero is a no-op."""
    if cycles > 0:
        await ClockCycles(tb.dut.clk, cycles)


async def _two_chiplets(tb: CtpTb, rng: random.Random, pattern: str) -> int:
    """Run one two-chiplet pull pattern; return the cycle of the first pull."""
    w0 = rng.randrange(2, 8)
    w1 = rng.randrange(2, 8)
    tb.log.info("pattern %s: chiplet 0 pulls %d cycles, chiplet 1 pulls %d cycles", pattern, w0, w1)
    if pattern == "simultaneous":
        start = await tb.drive_ext(0b11)
        await _hold(tb, min(w0, w1) - 1)
        await tb.drive_ext(0b10 if w1 > w0 else 0b01)
        await _hold(tb, abs(w1 - w0) - 1)
        await tb.drive_ext(0)
    elif pattern == "staggered":
        offset = rng.randrange(1, w0)
        start = await tb.drive_ext(0b01)
        await _hold(tb, offset - 1)
        await tb.drive_ext(0b11)
        await _hold(tb, w0 - offset - 1)
        await tb.drive_ext(0b10)
        await _hold(tb, w1 - 1)
        await tb.drive_ext(0)
    elif pattern == "adjacent":
        start = await tb.drive_ext(0b01)
        await _hold(tb, w0 - 1)
        # Chiplet 1 pulls in the very cycle chiplet 0 releases.
        await tb.drive_ext(0b10)
        await _hold(tb, w1 - 1)
        await tb.drive_ext(0)
    elif pattern == "gap_one":
        start = await tb.drive_ext(0b01)
        await _hold(tb, w0 - 1)
        await tb.drive_ext(0)
        # The wire rests for exactly one cycle before chiplet 1 pulls.
        await tb.drive_ext(0b10)
        await _hold(tb, w1 - 1)
        await tb.drive_ext(0)
    elif pattern == "separate":
        start = await tb.drive_ext(0b01)
        await _hold(tb, w0 - 1)
        await tb.drive_ext(0)
        await _hold(tb, rng.randrange(2, 10))
        await tb.drive_ext(0b10)
        await _hold(tb, w1 - 1)
        await tb.drive_ext(0)
    else:
        raise ValueError(f"unknown two-chiplet pattern {pattern!r}")
    return start


@cocotb.test()
async def ctp_wire_or_bus_test(dut) -> None:
    """Reset, INVERT writes, and several drivers on the shared wire."""
    tb = CtpTb(dut, name="ctp_wire_or_bus_test")
    seed = random_seed()
    rng = random.Random(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    tb.start_ct_dst_watcher()
    tb.receive.start()
    await tb.settle()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset on the shared wire")
    tb.log.info("=" * 70)
    tb.log.info("1a: the wire rests at its pull-up through reset")
    await tb.pulse_reset()
    await tb.receive.expect("reset with the wire resting", expected_count=0)

    tb.log.info("1b: chiplet 0 holds the wire asserted through reset")
    await tb.drive_ext(0b01)
    await tb.receive.expect("wire pulled before reset", expected_count=1)
    await tb.pulse_reset()
    await tb.receive.expect("reset release with the wire held asserted", expected_count=0)
    await tb.drive_ext(0)
    await tb.receive.expect("wire released after reset", expected_count=0)
    before = tb.ct_dst_pulses()
    start = await tb.ext_pulse(0, 4)
    await tb.expect_ct_dst_at(start, before, "first pull after the held reset")
    await tb.receive.expect("first pull after the held reset", expected_count=1)

    tb.log.info("1c: pull-down board brought up with INVERT=1")
    tb.set_wire_pull(1)
    await tb.settle()
    await tb.pulse_reset()
    await tb.receive.expect("reset on the pull-down board (INVERT reset to 0)", expected_count=0)
    await tb.write_config(mode=0, invert=1)
    await tb.receive.expect("INVERT=1 written with the wire resting low", expected_count=0)
    before = tb.ct_dst_pulses()
    start = await tb.ext_pulse(0, 3)
    await tb.expect_ct_dst_at(start, before, "first pull on the pull-down board")
    await tb.receive.expect("first pull on the pull-down board", expected_count=1)
    tb.set_wire_pull(0)
    await tb.settle()
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: INVERT written against a pull-up board")
    tb.log.info("=" * 70)
    await tb.write_config(mode=0, invert=1)
    await tb.receive.expect(
        "INVERT=1 written while the wire rests high: the sensed wire moves from rest to asserted",
        expected_count=1,
    )
    await tb.write_config(mode=0, invert=0)
    await tb.receive.expect("INVERT=0 written back while the wire rests high", expected_count=0)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: two external chiplets (%d patterns + %d seeded)", 5, N_RAND_ITER)
    tb.log.info("=" * 70)
    directed = list(TWO_DRIVER_PATTERNS)
    patterns = directed + [rng.choice(directed) for _ in range(N_RAND_ITER)]
    for index, pattern in enumerate(patterns):
        what = f"pattern {index} ({pattern})"
        before = tb.ct_dst_pulses()
        start = await _two_chiplets(tb, rng, pattern)
        expected = TWO_DRIVER_PATTERNS[pattern]
        await tb.expect_ct_dst_at(start, before, what, count=expected)
        await tb.receive.expect(what, expected_count=expected)
        await _hold(tb, rng.randrange(1, 6))

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: the port among the chiplets (%d seeded iterations)", N_RAND_ITER)
    tb.log.info("=" * 70)
    for index in range(N_RAND_ITER):
        stretch = rng.randrange(3, 13)
        await tb.write_stretch_mult(stretch)
        case = ("merged", "absorbed", "adjacent", "gap_one", "alone")[index % 5]
        tb.log.info("iter %d: STRETCH_MULT=%d, case %s", index, stretch, case)
        await tb.pulse_ct_src()
        await tb.wait_level(dut.ct_req_out_dout_en, 1, 20, f"iter {index}: port pulls")
        if case == "merged":
            # Chiplet 0 pulls inside the window and releases after it.
            await _hold(tb, rng.randrange(0, stretch))
            await tb.drive_ext(0b01)
            await tb.wait_level(
                dut.ct_req_out_dout_en, 0, stretch + 4, f"iter {index}: port releases"
            )
            await _hold(tb, rng.randrange(1, 5))
            await tb.drive_ext(0)
            expected = 1
        elif case == "absorbed":
            # Chiplet 0 pulls and releases inside the window.
            await _hold(tb, rng.randrange(0, stretch - 2))
            await tb.ext_pulse(0, 1)
            await tb.wait_level(
                dut.ct_req_out_dout_en, 0, stretch + 4, f"iter {index}: port releases"
            )
            expected = 1
        elif case == "adjacent":
            # The window is STRETCH_MULT+1 cycles from the rise seen on the
            # last falling edge; chiplet 0 pulls in the cycle the port releases.
            await ClockCycles(dut.clk, stretch + 1)
            tb.set_ext_now(0b01)
            await _hold(tb, rng.randrange(1, 5))
            await tb.drive_ext(0)
            expected = 1
        elif case == "gap_one":
            await tb.wait_level(
                dut.ct_req_out_dout_en, 0, stretch + 4, f"iter {index}: port releases"
            )
            # The wire rests for the release cycle; chiplet 0 pulls at the next edge.
            await tb.ext_pulse(0, rng.randrange(1, 5))
            expected = 2
        else:
            await tb.wait_level(
                dut.ct_req_out_dout_en, 0, stretch + 4, f"iter {index}: port releases"
            )
            expected = 1
        await ClockCycles(dut.clk, WINDOW_TAIL_CYCLES)
        await tb.receive.expect(f"iter {index} ({case})", expected_count=expected)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 5: model self-check — INVERT=1 on the pull-up board")
    tb.log.info("=" * 70)
    stretch = rng.randrange(2, 9)
    await tb.write_stretch_mult(stretch)
    await tb.write_config(mode=0, invert=1)
    await tb.settle()
    await tb.pulse_ct_src()
    await tb.wait_level(dut.ct_req_out_dout_en, 1, 20, "mismatch: port enables its pad")
    await tb.wait_level(dut.ct_req_out_dout_en, 0, stretch + 4, "mismatch: port releases")
    mismatch_cycles = await tb.receive.expect(
        "port drives the pull level", expected_count=0, allow_mismatch=True
    )
    assert mismatch_cycles == stretch + 1, (
        f"pull mismatch flagged for {mismatch_cycles} cycles, expected the {stretch + 1}-cycle window"
    )
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    tb.log.info("ctp_wire_or_bus_test PASSED (seed=%d)", seed)
