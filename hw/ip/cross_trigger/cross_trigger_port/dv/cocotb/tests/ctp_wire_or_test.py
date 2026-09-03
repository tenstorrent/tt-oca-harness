# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Port wire-OR mode: pad matrix, stretcher, receive, inversion.

Scenarios:

1. Pad enable matrix — wire-OR listens on the shared CT_Req_out wire only
   (interface spec table), and the pad data output idles at the static level
   for the configured INVERT sense.
2. Stretched transmit window — deterministic corners plus randomized
   STRETCH_MULT values; every core-side pulse yields a CT_Req_out enable
   window of exactly STRETCH_MULT+1 cycles with BUSY mirroring it.
3. Back-to-back restart — a second pulse inside the window reloads the
   stretcher, extending the window past a single pulse's length.
4. Receive — a wire excursion produces exactly one single-cycle ct_dst
   pulse at the LOGICAL rising edge (raw ^ INVERT), for both INVERT senses
   and both idle levels.

The stretched-window width (STRETCH_MULT+1) and the pad enable/static-data
levels come from the architecture/interface spec; the INVERT sense of the
inputs and outputs comes from the CONFIG.INVERT field description in
cross_trigger_port.rdl.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from ctp_base_test import (
    GPIO_SYNC_LATENCY,
    CtpTb,
    random_seed,
)

# Randomized-iteration floor for the stretch and restart sweeps.
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
    tb = CtpTb(dut, name="ctp_wire_or_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    tb.start_ct_dst_watcher()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: pad enable matrix and static data output, both INVERT senses")
    tb.log.info("=" * 70)
    for invert in (0, 1):
        # The pad data input must sit at the logical-idle level for the new
        # sense BEFORE the sense flips, so the receive path sees no edge.
        dut.ct_req_out_din.value = invert
        await tb.write_config(mode=0, invert=invert)
        await tb.settle()
        tb.check_pad_enables("wire_or")
        dout_en = int(dut.ct_req_out_dout_en.value)
        assert dout_en == 0, f"wire-OR idle: dout_en expected 0, observed {dout_en}"
        # Spec: wire-OR holds the pad data output static-low; RDL CONFIG.INVERT
        # inverts all pad data outputs, so INVERT=1 holds it static-high.
        dout = int(dut.ct_req_out_dout.value)
        assert dout == invert, (
            f"wire-OR static data output: INVERT={invert} expects {invert}, observed {dout}"
        )
        tb.log.info("INVERT=%d: enables and static dout=%d match the spec", invert, dout)
    dut.ct_req_out_din.value = 0
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: stretched transmit window (corners + %d randomized)", N_RAND_ITER)
    tb.log.info("=" * 70)
    stretch_values = [0, 1, 2, 100] + [random.randrange(0, 301) for _ in range(N_RAND_ITER)]
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
    pulses = tb.ct_dst_pulses()
    assert pulses == 0, f"transmit-only traffic must not pulse ct_dst (observed {pulses})"

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: back-to-back restart (%d randomized iterations)", N_RAND_ITER)
    tb.log.info("=" * 70)
    for index in range(N_RAND_ITER):
        stretch = random.randrange(8, 41)
        delay = random.randrange(2, stretch - 2)
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

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: receive — one ct_dst pulse per wire excursion, all senses")
    tb.log.info("=" * 70)
    n_excursions = 6
    for invert in (0, 1):
        for idle_logical in (0, 1):
            # Raw pad level for a given logical level under this sense.
            idle_raw = idle_logical ^ invert
            active_raw = idle_raw ^ 1
            # Park the wire at the new idle, then flip the sense, then let the
            # synchronizers flush; settle() clears any transition pulses.
            dut.ct_req_out_din.value = idle_raw
            await tb.write_config(mode=0, invert=invert)
            await tb.settle()
            tb.log.info(
                "INVERT=%d idle_logical=%d: %d excursions, ct_dst expected at the "
                "logical rising edge (%s edge of the raw wire)",
                invert,
                idle_logical,
                n_excursions,
                "assert" if idle_logical == 0 else "deassert",
            )
            for excursion in range(n_excursions):
                width = random.randrange(3, 11)
                gap = random.randrange(3, 16)
                before = tb.ct_dst_pulses()
                await RisingEdge(dut.clk)
                dut.ct_req_out_din.value = active_raw
                if idle_logical == 0:
                    # Logical rising edge at the assert edge.
                    await tb.wait_level(
                        dut.ct_dst,
                        1,
                        GPIO_SYNC_LATENCY,
                        f"receive INVERT={invert} idle={idle_logical} exc {excursion}",
                    )
                await ClockCycles(dut.clk, width)
                dut.ct_req_out_din.value = idle_raw
                if idle_logical == 1:
                    # Logical rising edge at the deassert (return-to-idle) edge.
                    await tb.wait_level(
                        dut.ct_dst,
                        1,
                        GPIO_SYNC_LATENCY,
                        f"receive INVERT={invert} idle={idle_logical} exc {excursion}",
                    )
                await ClockCycles(dut.clk, gap + GPIO_SYNC_LATENCY)
                observed = tb.ct_dst_pulses() - before
                assert observed == 1, (
                    f"receive INVERT={invert} idle_logical={idle_logical} excursion "
                    f"{excursion} (width={width}): expected exactly 1 ct_dst pulse, "
                    f"observed {observed}"
                )
    dut.ct_req_out_din.value = 0
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    tb.log.info("ctp_wire_or_test PASSED (seed=%d)", seed)
