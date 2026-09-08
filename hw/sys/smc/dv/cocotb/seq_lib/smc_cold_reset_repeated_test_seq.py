# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_cold_reset_repeated_test (3 re-asserts).

Each re-assert is proven at both ends, so a DUT that never takes the cold or
cool reset fails instead of coasting to the post-release SAMPLE gates
([NO-ALWAYS-PASS-CHECKER]):

* assert half: a bounded ``WAIT_STATE`` on the asserted levels. It doubles as
  the stimulus hold -- ``smc_reset_ctrl`` de-glitches ``rst_cold_ni`` /
  ``rst_cool_ni`` over 32 ``clk_ref_i`` samples, so a fixed hold shorter than
  that window is silently rejected and resets nothing. Holding until the reset
  is *observed* cannot be short.
* hold half: after the wait matched, the pin stays low across a further
  ``MID_ASSERT_HOLD_REF_CYCLES`` ``clk_ref_i`` edges and EVERY one of those
  samples must still read the asserted levels. This is a separate observation
  in time from the wait (the wait's match and a RAW_SAMPLE dispatched straight
  after it land in the same delta region, so such a snapshot could not fail
  unless the wait already had -- [NO-ALWAYS-PASS-CHECKER]). A DUT that releases
  the cold/cool path early, anywhere inside the window, fails here.
* release half: a bounded ``WAIT_STATE`` on the released levels followed by the
  post-release ``SAMPLE`` (the checked_cleared leg); no fixed ``ClockCycles``
  completion sync ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).

Expected levels come from ``hw/sys/smc/doc/clk_rst.adoc``: cold reset drives the
cold-stable and primary paths, cool reset is a primary-level reset that leaves
the cold-stable path released.
"""

from __future__ import annotations

from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase


class smc_cold_reset_repeated_test_seq(SmcResetSeqBase):
    REPEATS = 3
    # Ceilings for the bounded waits, never the checked quantity: the assert
    # bound must exceed the 32-sample de-glitch window plus the 4-stage output
    # synchronizers, the release bound the cold-reset extender.
    ASSERT_BOUND_REF_CYCLES = 400
    RELEASE_BOUND_REF_CYCLES = 2000
    # Mid-assert hold window, in clk_ref_i edges: as wide as smc_reset_ctrl's
    # 32-sample de-glitch window, so an incorrect release that took a full
    # de-glitch to appear is still inside the checked window.
    MID_ASSERT_HOLD_REF_CYCLES = 32

    # `_send` (with its `expect_*` keyword guard), `_hold_raw` and
    # `_wait_released` come from SmcResetSeqBase so the guard is defined once
    # for the whole reset family ([REUSE-AND-LAYERING]).

    async def body(self) -> None:
        await self._send(SmcResetOp.SAMPLE)
        for _ in range(self.REPEATS):
            await self._send(SmcResetOp.COLD_RST_LO)
            # Cold assert observed: cold-stable and both primary resets low
            # while power-good stays qualified.
            await self._send(
                SmcResetOp.WAIT_STATE,
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=0,
                expect_rst_primary_ref_clk_n=0,
                expect_rst_primary_smc_clk_n=0,
                expect_left_stable=True,
                timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
            )
            # Still asserted while rst_cold_ni is held low, at every sample of a
            # real (time-advancing) window: a DUT that releases the cold path
            # early fails inside the hold.
            await self._hold_raw(
                "cold assert",
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=0,
                expect_rst_primary_ref_clk_n=0,
                expect_rst_primary_smc_clk_n=0,
                expect_left_stable=True,
            )
            await self._send(SmcResetOp.COLD_RST_HI)
            await self._wait_released()
            await self._send(SmcResetOp.SAMPLE)
        # Exercise the cool-reset op set so the scoreboard sees the full
        # reset_op range -- with the same assert/release proof as the cold legs.
        await self._send(SmcResetOp.COOL_RST_LO)
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
        )
        await self._hold_raw(
            "cool assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        await self._wait_released()
        await self._send(SmcResetOp.SAMPLE)
        # Activity gate on the fail-capable legs: one assert + one release wait
        # per cold repeat plus the cool pair, and a full checked mid-assert hold
        # window each ([NO-ZERO-ACTIVITY-PASS]). The raw floor counts the
        # samples taken *after* the assert handshake, so it cannot be satisfied
        # by snapshots that shared the wait's timestamp.
        sb = self.env.scoreboard
        expected_waits = 2 * (self.REPEATS + 1)
        assert sb.reset_wait_checks_seen >= expected_waits, (
            f"expected {expected_waits} bounded reset WAIT_STATE checks, "
            f"scoreboard saw {sb.reset_wait_checks_seen}"
        )
        expected_raw = (self.REPEATS + 1) * self.MID_ASSERT_HOLD_REF_CYCLES
        assert sb.reset_raw_checks_seen >= expected_raw, (
            f"expected {expected_raw} checked mid-assert hold samples "
            f"({self.REPEATS + 1} legs x {self.MID_ASSERT_HOLD_REF_CYCLES} "
            f"clk_ref_i edges), scoreboard saw {sb.reset_raw_checks_seen}"
        )
