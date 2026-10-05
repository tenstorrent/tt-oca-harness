# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Canonical reset recovery matrix sequence.

This sequence compresses the reset-depth variants into one coverage-oriented
scenario: baseline sample, powergood glitch, cold-reset reassert, cool-reset
pulse, and final recovery sample.

Every leg of the matrix is fail-capable at both ends:

* the assert half rides an exact expectation on the reset item, so a DUT that
  never asserts the driven reset fails there instead of leaving an
  OBSERVED-ONLY snapshot behind ([NO-ALWAYS-PASS-CHECKER]). The expected values
  come from ``hw/sys/smc/doc/clk_rst.adoc`` (POR holds the functional reset
  gated until power-good is stable; cool reset is a primary-level reset, so it
  asserts ``rst_primary_*`` while the cold-stable path stays released).
* the "still asserted while the pin/level is held" half is a *hold*, not a
  single sample: all ``MID_ASSERT_HOLD_REF_CYCLES`` samples of the driven
  window must carry the asserted levels. One instantaneous snapshot passes for
  a DUT that releases the driven reset at any other instant of the same
  window, so each of the three legs checks the whole window instead
  ([EXACT-EXPECTATION]).
* the recovery half is a bounded ``WAIT_STATE`` handshake on the released
  levels, not a fixed settle: expiry raises with the last observed state
  ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).

The assert waits double as the stimulus hold: ``smc_reset_ctrl`` de-glitches
``rst_cold_ni`` / ``rst_cool_ni`` over 32 ``clk_ref_i`` samples, so the pin is
held low until the reset is *observed*, never for a fixed count that could be
shorter than the de-glitch window (silently rejected, resetting nothing).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase


class smc_reset_recovery_matrix_test_seq(SmcResetSeqBase):
    """Exercise the canonical reset/powergood recovery matrix."""

    # Ceilings for the bounded waits, never the checked quantity. The assert
    # bound must exceed the 32-sample cold/cool de-glitch window plus the
    # 4-stage output synchronizers; the recovery bound covers power-good
    # re-qualification and the cold-reset extender.
    ASSERT_BOUND_REF_CYCLES = 400
    RELEASE_BOUND_REF_CYCLES = 2000
    # Width of every "still asserted while the pin/level is held" window, in
    # clk_ref_i edges, and therefore also the stimulus low time of each leg
    # (the pin/level is restored only after the window closes). As wide as
    # smc_reset_ctrl's 32-sample de-glitch window: a DUT that releases the
    # driven reset at *any* sample inside the hold fails ([EXACT-EXPECTATION]).
    MID_ASSERT_HOLD_REF_CYCLES = 32
    # Held mid-assert legs, each contributing a full checked window to the
    # scoreboard's reset_raw_checks_seen floor below.
    MID_ASSERT_LEGS = 3

    async def _recover_and_sample(self) -> SmcResetItem:
        await self._wait_released()
        return await self._send(SmcResetOp.SAMPLE)

    async def body(self) -> None:
        dut = cocotb.top

        await self._send(SmcResetOp.SAMPLE)

        # --- powergood glitch: POR gates the functional reset path -----------
        await self._send(SmcResetOp.POWERGOOD_LO)
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
        )
        # Held, not sampled once: powergood_i stays low for the whole window and
        # EVERY sample must still show the functional reset path gated.
        await self._hold_raw(
            "powergood glitch (POR gates the functional reset path)",
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.POWERGOOD_HI)
        # Transition diagnostics only (booked OBSERVED-ONLY by the scoreboard):
        # the recovery verdict is the WAIT_STATE inside _recover_and_sample.
        for offset in (2, 8, 20, 45, 120):
            await ClockCycles(dut.clk_ref_i, offset)
            await self._send(SmcResetOp.RAW_SAMPLE)
        await self._recover_and_sample()

        # --- cold reset re-assert -------------------------------------------
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
        )
        # Still held low at EVERY sample of the window (not one instant):
        # power-good stays qualified while the cold path resets, and a DUT that
        # releases the cold path early anywhere inside the driven hold fails.
        await self._hold_raw(
            "cold re-assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._raw_after(8)
        await self._raw_after(32)
        await self._recover_and_sample()

        # --- cool reset pulse (primary-level reset, cold path untouched) -----
        await self._send(SmcResetOp.COOL_RST_LO)
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
        )
        # Held for the whole window: cool is a primary-level reset, so the
        # cold-stable path must stay released at every sample while both primary
        # resets stay asserted.
        await self._hold_raw(
            "cool pulse (primary-level reset)",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        await self._raw_after(16)
        await self._recover_and_sample()

        # The activity gate counts only the fail-capable legs, so the
        # expectation-free transition snapshots cannot satisfy it
        # ([NO-ZERO-ACTIVITY-PASS]); `resolvable` on every checked item is
        # asserted by the scoreboard.
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= 6, (
            f"expected 6 bounded reset WAIT_STATE checks (3 asserts + 3 "
            f"recoveries), scoreboard saw {sb.reset_wait_checks_seen}"
        )
        expected_raw = self.MID_ASSERT_LEGS * self.MID_ASSERT_HOLD_REF_CYCLES
        assert sb.reset_raw_checks_seen >= expected_raw, (
            f"expected {expected_raw} checked mid-assert reset samples "
            f"({self.MID_ASSERT_LEGS} held legs x "
            f"{self.MID_ASSERT_HOLD_REF_CYCLES} clk_ref_i edges), scoreboard "
            f"saw {sb.reset_raw_checks_seen}"
        )
