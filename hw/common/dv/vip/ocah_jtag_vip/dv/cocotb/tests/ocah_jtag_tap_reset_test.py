# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared JTAG VIP selftest: TAP reset and state against the reference model.

The reactive device's TAP controller state is the observable: a TMS-high
reset lands it in Test-Logic-Reset, every step of a random TMS walk matches
the reference model, five or more TMS-high cycles reach Test-Logic-Reset from
any start state, asserting TRST lands the device in Test-Logic-Reset and a DR
scan after release returns IDCODE with no instruction loaded. A reset that
did not reach Test-Logic-Reset handed to a fail-fast checker must be rejected.

``OCAH_JTAG_SELFTEST_NEGATIVE`` desynchronizes the reference model before the
walk so the first ``CHK-TAP-STATE`` fails and the run must fail.
"""

from __future__ import annotations

import logging
import os
import random

import cocotb
from ocah_jtag_vip import OcahJtagState
from ocah_jtag_vip_harness import (
    IDCODE,
    IDCODE_MASK,
    IDCODE_WIDTH,
    JtagHarness,
    build_stack,
    negative_armed,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_jtag_tap_reset_test")

REQUIRED_IDS = (
    "CHK-TAP-RESET-TLR",
    "CHK-TAP-STATE",
    "CHK-TAP-TLR-TMS5",
    "CHK-SLAVE-STATE",
    "CHK-JTAG-TRST-TLR",
    "CHK-JTAG-TRST-IDCODE",
    "CHK-JTAG-NEG-STATE",
)


async def _random_walk(harness: JtagHarness, rng: random.Random, steps: int) -> None:
    """Step random TMS values and judge the device state after each against the model."""
    for index in range(steps):
        tms = rng.randint(0, 1)
        await harness.master.step(tms)
        harness.checker.check_state_step(
            tms, harness.slave.device_state(), context=f"walk step {index}"
        )


async def _tms_high_resets(harness: JtagHarness, rng: random.Random) -> None:
    """From several start states, five to eight TMS-high cycles must reach TLR."""
    starts = [
        OcahJtagState.RUN_TEST_IDLE,
        OcahJtagState.SHIFT_IR,
        OcahJtagState.SHIFT_DR,
        rng.choice([OcahJtagState.PAUSE_IR, OcahJtagState.PAUSE_DR]),
    ]
    for state in starts:
        await harness.master.goto_state(state)
        harness.checker.sync_state(state)
        harness.slave.check_state(state, context="after goto_state")
        ones = rng.randint(5, 8)
        for _ in range(ones):
            await harness.master.step(1)
        harness.checker.check_tms_ones_to_tlr(
            ones, harness.slave.device_state(), context=f"from={state.name}"
        )


@cocotb.test()
async def ocah_jtag_tap_reset_test(dut) -> None:
    rng = scenario_rng("tap_reset")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log, item_checks=False)
    seq, slave, checker = harness.master, harness.slave, harness.checker
    steps = int(os.environ.get("OCAH_JTAG_WALK_STEPS", "48"))
    negative = negative_armed()
    log.info("start: reset, %d-step walk, TMS-high resets, TRST, negative probe", steps)

    await seq.reset_to_tlr()
    checker.check_reset_to_tlr(slave.device_state(), context="TMS-high reset at start")

    if negative:
        log.warning(
            "NEGATIVE VALIDATION: desynchronizing the reference model to SHIFT_DR "
            "before the walk; the first CHK-TAP-STATE must fail"
        )
        checker.sync_state(OcahJtagState.SHIFT_DR)
    await _random_walk(harness, rng, steps)
    await _tms_high_resets(harness, rng)

    await seq.goto_state(OcahJtagState.SHIFT_DR)
    checker.sync_state(OcahJtagState.SHIFT_DR)
    await seq.assert_trst(tck_cycles=2)
    checker.expect_equal(
        "CHK-JTAG-TRST-TLR",
        int(slave.device_state()),
        int(OcahJtagState.TEST_LOGIC_RESET),
        context=f"device={slave.device_state().name} after TRST from SHIFT_DR",
    )
    await seq.release_trst(tck_cycles=1)
    observed = await seq.shift_dr(0, IDCODE_WIDTH, back_to_rti=True)
    checker.expect_equal(
        "CHK-JTAG-TRST-IDCODE",
        observed & IDCODE_MASK,
        IDCODE,
        context="DR scan after TRST release, no IR load",
    )

    rejected = rejects(
        "state",
        lambda probe: probe.check_reset_to_tlr(
            OcahJtagState.RUN_TEST_IDLE, context="a reset that did not reach TLR"
        ),
    )
    checker.expect_true(
        "CHK-JTAG-NEG-STATE", rejected, context="a reset outside TLR must be rejected"
    )

    await harness.stop()
    checker.finalize()
