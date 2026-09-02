# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Network clock stop: OR aggregation and JTAG discrimination.

Contract (CTN clock-stop control): ``cla_clock_stop`` is the combinational OR
of the CLA requests only; ``stop_clks`` is the synchronized, registered OR of
the CLA requests AND the JTAG clock stop, so it asserts a few cycles after a
request and must hold while any request is pending.

Scenarios:

1. Reset state — both outputs low.
2. Walking-one over every CLA request bit — each bit alone asserts both
   outputs; clearing it releases both.
3. JTAG discrimination — jtag_clock_stop asserts stop_clks while
   cla_clock_stop stays low (the JTAG path is not a CLA request).
4. Randomized subsets — random CLA vectors and JTAG level, checked against
   the OR model, including one-at-a-time decay from all-ones.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from ctn_base_test import (
    NUM_CLK_STOP_REQ,
    CtnTb,
    random_seed,
)

# stop_clks path: OR tree -> 2-FF synchronizer -> output register.
STOP_CLKS_LATENCY = 6
N_RAND_ITER = 16


async def _expect_stop_state(tb, cla_vector: int, jtag: int, what: str) -> None:
    """Apply one request state and check both outputs against the OR model."""
    dut = tb.dut
    tb.set_input("clk_stop_req", cla_vector)
    dut.jtag_clock_stop.value = jtag
    expected_stop = 1 if (cla_vector or jtag) else 0
    expected_cla = 1 if cla_vector else 0
    await tb.wait_bit(dut.stop_clks, 0, expected_stop, STOP_CLKS_LATENCY, f"{what}: stop_clks")
    # cla_clock_stop is combinational on the request OR tree.
    observed_cla = int(dut.cla_clock_stop.value)
    assert observed_cla == expected_cla, (
        f"{what}: cla_clock_stop expected {expected_cla} for req=0x{cla_vector:03x}, "
        f"observed {observed_cla}"
    )
    # Both outputs must hold steady while the request state persists.
    for _ in range(4):
        await ClockCycles(dut.clk, 1)
        assert int(dut.stop_clks.value) == expected_stop, f"{what}: stop_clks not stable"
        assert int(dut.cla_clock_stop.value) == expected_cla, f"{what}: cla_clock_stop not stable"


@cocotb.test()
async def ctn_clock_stop_test(dut) -> None:
    tb = CtnTb(dut, name="ctn_clock_stop_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset state")
    tb.log.info("=" * 70)
    assert int(dut.stop_clks.value) == 0, "stop_clks must be 0 out of reset"
    assert int(dut.cla_clock_stop.value) == 0, "cla_clock_stop must be 0 out of reset"

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: walking-one over %d CLA request bits", NUM_CLK_STOP_REQ)
    tb.log.info("=" * 70)
    for bit in range(NUM_CLK_STOP_REQ):
        tb.log.info("request bit %d alone: expect both outputs asserted", bit)
        await _expect_stop_state(tb, 1 << bit, 0, f"walking-one bit {bit} set")
        await _expect_stop_state(tb, 0, 0, f"walking-one bit {bit} cleared")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: JTAG clock stop discriminates from CLA requests")
    tb.log.info("=" * 70)
    await _expect_stop_state(tb, 0, 1, "jtag only (stop_clks=1, cla_clock_stop=0)")
    await _expect_stop_state(tb, 0, 0, "jtag cleared")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: randomized request subsets (%d iterations) and decay", N_RAND_ITER)
    tb.log.info("=" * 70)
    for index in range(N_RAND_ITER):
        cla_vector = random.getrandbits(NUM_CLK_STOP_REQ)
        jtag = random.randrange(2)
        tb.log.info("iter %d: req=0x%03x jtag=%d", index, cla_vector, jtag)
        await _expect_stop_state(tb, cla_vector, jtag, f"random iter {index}")
    await _expect_stop_state(tb, 0, 0, "random sweep cleared")

    tb.log.info("decay: all-ones, then drop one request at a time")
    remaining = (1 << NUM_CLK_STOP_REQ) - 1
    await _expect_stop_state(tb, remaining, 0, "decay all-ones")
    while remaining:
        remaining &= remaining - 1  # clear the lowest set bit
        await _expect_stop_state(tb, remaining, 0, f"decay remaining=0x{remaining:03x}")

    tb.log.info("ctn_clock_stop_test PASSED (seed=%d)", seed)
