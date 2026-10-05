# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_powergood_glitch_test.

Exercises the SMC powergood stretcher: sample baseline, drive powergood low,
prove the DUT actually left its post-stable state while power-good is not
stable, restore powergood high, then wait -- bounded, fail-on-expiry -- until
every reset observable is released again and sample.

Two proof properties, both fail-capable:

* mid-glitch (``clk_rst.adoc`` "SMC reset sources and effects": power-good
  low "Holds functional reset and resets the JTAG/TDR POR path"): with
  ``powergood_stable_o==0`` the cold-stable and both primary resets must read
  asserted -- and at **every** sample of the glitch, not at one instant, since
  a single snapshot also passes for a DUT that releases the functional reset
  path anywhere else inside the same window ([EXACT-EXPECTATION]). Those
  expectations ride on the reset items, so the scoreboard -- not this sequence
  -- owns the verdict, and a DUT that ignores ``powergood_i`` fails instead of
  producing an OBSERVED-ONLY snapshot.
* recovery: a ``WAIT_STATE`` handshake on the released levels, so recovery
  latency is bounded and expiry raises with the last observed state ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase


class smc_powergood_glitch_test_seq(SmcResetSeqBase):
    # Width of the mid-glitch hold, in clk_ref_i edges, and therefore also how
    # long powergood_i stays low (it is restored only after the window closes).
    # As wide as smc_reset_ctrl's 32-sample de-glitch window: the gated state is
    # proven at EVERY sample of the glitch, so a DUT that lets the functional
    # reset path release at any instant while power-good is unstable fails
    # ([EXACT-EXPECTATION]).
    MID_GLITCH_HOLD_REF_CYCLES = 32

    # Stimulus-derived floors on the scoreboard's fail-capable counters. Without
    # them nothing in this test would notice if the glitch/recovery legs stopped
    # carrying expectations: the two bookend SAMPLEs and the 11 OBSERVED-ONLY
    # transition snapshots satisfy the global check_phase activity gate on their
    # own ([LIVENESS-COMPLETENESS] / [NO-ZERO-ACTIVITY-PASS]).
    MIN_WAIT_CHECKS = 2  # glitch-effect + recovery handshakes
    MIN_RAW_CHECKS = MID_GLITCH_HOLD_REF_CYCLES  # the whole checked hold window

    # powergood_stable_o is the stretcher's asynchronously-asserted output, so
    # the glitch must be visible within a few clk_ref_i edges; the bound is a
    # generous ceiling, never the checked quantity.
    GLITCH_EFFECT_BOUND_REF_CYCLES = 64
    # Recovery re-qualifies power-good and then walks the cold-reset extender
    # before primary is released, which takes a few hundred clk_ref_i edges. The
    # bound only has to be a safe ceiling -- expiry fails the test with the last state.
    RECOVER_BOUND_REF_CYCLES = 2000

    def __init__(self, name: str = "smc_powergood_glitch_test_seq") -> None:
        super().__init__(name)
        self.baseline_sample: SmcResetItem | None = None
        self.recovered_sample: SmcResetItem | None = None

    async def body(self) -> None:
        dut = cocotb.top
        self.baseline_sample = await self._send(SmcResetOp.SAMPLE)

        await self._send(SmcResetOp.POWERGOOD_LO)
        # FAIL-ON for a DUT that ignores powergood_i: the glitch must move the
        # design off the fully post-stable state within a bounded window.
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.GLITCH_EFFECT_BOUND_REF_CYCLES,
        )
        # Hold the rest of the glitch and check the gated state exactly at EVERY
        # sample of it, not once: while power-good is not stable the cold-stable
        # and both primary resets must be asserted for the whole window, so an
        # early release anywhere inside the glitch fails.
        await self._hold_raw(
            "powergood glitch (POR gates the functional reset path)",
            hold=self.MID_GLITCH_HOLD_REF_CYCLES,
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.POWERGOOD_HI)
        # Recovery transition diagnostics: the stretcher releases bits over a
        # span of cycles, so these snapshots harvest reset-state diversity in
        # the (powergood, cold_stable, primary_ref, primary_smc) space. They
        # carry no expectation -- the scoreboard books them OBSERVED-ONLY, they
        # are not evidence, and the recovery verdict is the WAIT_STATE below.
        already_waited = 0
        for offset in (1, 3, 5, 8, 12, 16, 22, 30, 45, 70, 120):
            delta = offset - already_waited
            if delta > 0:
                await ClockCycles(dut.clk_ref_i, delta)
                already_waited = offset
            await self._send(SmcResetOp.RAW_SAMPLE)
        # Handshake, not a settle: every reset observable back to released.
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=1,
            expect_rst_primary_smc_clk_n=1,
            expect_rst_wdt_smc_clk_n=1,
            timeout_ref_cycles=self.RECOVER_BOUND_REF_CYCLES,
        )

        self.recovered_sample = await self._send(SmcResetOp.SAMPLE)

        # Activity gate on the fail-capable legs only: the 11 transition
        # snapshots above are booked OBSERVED-ONLY and cannot satisfy either
        # floor, so a regression that silently stopped comparing the glitch or
        # recovery expectations fails here instead of passing on the bookends.
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= self.MIN_WAIT_CHECKS, (
            f"expected {self.MIN_WAIT_CHECKS} bounded reset WAIT_STATE checks "
            f"(glitch effect + recovery), scoreboard saw "
            f"{sb.reset_wait_checks_seen}"
        )
        assert sb.reset_raw_checks_seen >= self.MIN_RAW_CHECKS, (
            f"expected {self.MIN_RAW_CHECKS} checked mid-glitch reset samples "
            f"(the full {self.MID_GLITCH_HOLD_REF_CYCLES}-edge hold window), "
            f"scoreboard saw {sb.reset_raw_checks_seen} (expectation-free "
            f"snapshots are booked separately and do not count)"
        )
