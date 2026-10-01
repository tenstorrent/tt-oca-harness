# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Port wire-OR mode: pad matrix, stretcher, receive, inversion.

Scenarios:

1. Pad enable matrix — wire-OR listens on the shared CT_Req_out wire only
   (interface spec table), and the pad data output rests at the asserted
   level of the configured INVERT sense, ready to pull the wire when the
   enable opens.
2. Stretched transmit window — deterministic corners plus randomized
   STRETCH_MULT values; every core-side pulse yields a CT_Req_out enable
   window of exactly STRETCH_MULT+1 cycles with BUSY mirroring it, and the
   port hears its own pull on the shared wire as one trigger at the
   assertion edge.
3. Back-to-back restart — a second pulse inside the window reloads the
   stretcher, extending the window past a single pulse's length; the wire
   stays asserted throughout, so the port hears one trigger.
4. Receive — an external chiplet pulls the shared wire; the port delivers
   exactly one single-cycle ct_dst pulse CT_DST_LATENCY cycles after the
   assertion edge and nothing at the release, for both INVERT senses on the
   matching board pull, down to a single-cycle pull.

The stretched-window width (STRETCH_MULT+1) and the pad enable/static-data
levels come from the architecture/interface spec; the wire polarity of each
INVERT sense comes from the CONFIG.INVERT field description in
cross_trigger_port.rdl. Every ct_dst pulse is compared cycle for cycle with
the wire-OR receive model in ctp_base_test.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from ctp_base_test import (
    WIRE_OR_POLARITY,
    CtpTb,
    random_seed,
)

# Randomized-iteration floor for the stretch, restart, and receive sweeps.
N_RAND_ITER = 16


async def _measure_window(tb, what: str) -> int:
    """Measure the CT_Req_out enable window, checking BUSY mirrors it.

    Both pins are registered copies of the stretcher output, so they must
    agree at every falling-edge sample of the window.
    """
    dut = tb.dut
    cycles = 0
    while int(dut.ct_req_out_dout_en.value) == 1:
        assert int(dut.busy.value) == 1, (
            f"{what}: busy pin dropped at window cycle {cycles} "
            "while ct_req_out_dout_en is still high"
        )
        cycles += 1
        assert cycles <= 2000, f"{what}: window never closed after 2000 cycles"
        await FallingEdge(dut.clk)
    assert int(dut.busy.value) == 0, f"{what}: busy pin still high after the window closed"
    return cycles


@cocotb.test()
async def ctp_wire_or_test(dut) -> None:
    """Wire-OR pad matrix, stretched transmit, restart, and receive on the shared wire."""
    tb = CtpTb(dut, name="ctp_wire_or_test")
    seed = random_seed()
    rng = random.Random(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    tb.start_ct_dst_watcher()
    tb.receive.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: pad enable matrix and resting data output, both INVERT senses")
    tb.log.info("=" * 70)
    for invert in (0, 1):
        # The board comes first, then software sets INVERT to match it. The
        # bench's board swap moves the wire, so each step settles against the
        # receive model before the checks.
        tb.set_wire_pull(invert)
        await tb.settle()
        await tb.write_config(mode=0, invert=invert)
        await tb.settle()
        tb.check_pad_enables("wire_or")
        dout_en = int(dut.ct_req_out_dout_en.value)
        assert dout_en == 0, f"wire-OR idle: dout_en expected 0, observed {dout_en}"
        # The pad data output rests at the level the port pulls the wire to.
        expected_dout = WIRE_OR_POLARITY[invert].assert_level
        dout = int(dut.ct_req_out_dout.value)
        assert dout == expected_dout, (
            f"wire-OR data output: INVERT={invert} expects the asserted level "
            f"{expected_dout}, observed {dout}"
        )
        tb.log.info("INVERT=%d: enables and resting dout=%d match the spec", invert, dout)
    tb.set_wire_pull(0)
    await tb.settle()
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: stretched transmit window (corners + %d randomized)", N_RAND_ITER)
    tb.log.info("=" * 70)
    stretch_values = [0, 1, 2, 100] + [rng.randrange(0, 301) for _ in range(N_RAND_ITER)]
    for index, stretch in enumerate(stretch_values):
        await tb.write_stretch_mult(stretch)
        tb.log.info("iter %d: pulse ct_src, expect a %d-cycle window", index, stretch + 1)
        await tb.pulse_ct_src()
        await tb.wait_level(dut.ct_req_out_dout_en, 1, 20, f"stretch iter {index}: window assert")
        # For windows long enough to cover a CSR read, sample STATUS.BUSY
        # mid-window concurrently with the pin measurement.
        status_task = None
        if stretch >= 60:
            status_task = cocotb.start_soon(tb.read_status())
        window = await _measure_window(tb, f"stretch iter {index} (STRETCH_MULT={stretch})")
        tb.log.info("iter %d: observed window %d cycles (expected %d)", index, window, stretch + 1)
        assert window == stretch + 1, (
            f"stretch iter {index}: window {window} cycles != STRETCH_MULT+1 = {stretch + 1}"
        )
        if status_task is not None:
            status = await status_task
            assert status["busy"] == 1, (
                f"stretch iter {index}: STATUS.BUSY read mid-window expected 1"
            )
        # The port's own pull is one assertion of the shared wire.
        await tb.receive.expect(f"stretch iter {index}: own pull heard", expected_count=1)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: back-to-back restart (%d randomized iterations)", N_RAND_ITER)
    tb.log.info("=" * 70)
    for index in range(N_RAND_ITER):
        stretch = rng.randrange(8, 41)
        delay = rng.randrange(2, stretch - 2)
        await tb.write_stretch_mult(stretch)
        tb.log.info(
            "iter %d: STRETCH_MULT=%d, second pulse after %d cycles inside the window",
            index,
            stretch,
            delay,
        )
        await tb.pulse_ct_src()
        await tb.wait_level(dut.ct_req_out_dout_en, 1, 20, f"restart iter {index}: window assert")
        # Count the head of the window, inject the second pulse, then keep
        # counting the same continuous window to its end.
        head = 0
        while head < delay:
            assert int(dut.ct_req_out_dout_en.value) == 1, (
                f"restart iter {index}: window closed after only {head} cycles, "
                f"before the second pulse at {delay}"
            )
            head += 1
            await FallingEdge(dut.clk)
        await tb.pulse_ct_src()
        window = head + await _measure_window(tb, f"restart iter {index}")
        # The reload lands within a cycle or two of the injected pulse (half a
        # cycle of falling-edge sampling skew plus the pulse register), so the
        # continuous window is delay + (STRETCH_MULT+1) within that skew — and
        # always strictly longer than a single un-restarted window.
        low = delay + stretch + 1
        high = delay + stretch + 4
        tb.log.info(
            "iter %d: observed continuous window %d cycles (expected %d..%d)",
            index,
            window,
            low,
            high,
        )
        assert window > stretch + 1, (
            f"restart iter {index}: window {window} did not extend past a single "
            f"pulse's {stretch + 1} cycles — the stretcher did not restart"
        )
        assert low <= window <= high, (
            f"restart iter {index}: window {window} outside expected {low}..{high} "
            f"(STRETCH_MULT={stretch}, second pulse at {delay})"
        )
        # One continuous pull of the wire, whatever the number of source pulses.
        await tb.receive.expect(f"restart iter {index}: one wire assertion", expected_count=1)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: receive — one ct_dst per wire assertion, at the assertion edge")
    tb.log.info("=" * 70)
    await tb.write_stretch_mult(0)
    for invert in (0, 1):
        tb.set_wire_pull(invert)
        await tb.settle()
        await tb.write_config(mode=0, invert=invert)
        await tb.settle()
        polarity = WIRE_OR_POLARITY[invert]
        widths = [1, 2, 3] + [rng.randrange(1, 11) for _ in range(N_RAND_ITER)]
        tb.log.info(
            "INVERT=%d: wire rests at %d, an external chiplet pulls it to %d for %s cycles",
            invert,
            polarity.pull,
            polarity.assert_level,
            widths,
        )
        for index, width in enumerate(widths):
            gap = rng.randrange(1, 12)
            before = tb.ct_dst_pulses()
            start = await tb.ext_pulse(0, width)
            await tb.expect_ct_dst_at(
                start, before, f"receive INVERT={invert} pull {index} (width {width})"
            )
            await ClockCycles(dut.clk, gap)
        await tb.receive.expect(f"receive INVERT={invert}", expected_count=len(widths))
    tb.set_wire_pull(0)
    await tb.settle()
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    tb.log.info("ctp_wire_or_test PASSED (seed=%d)", seed)
