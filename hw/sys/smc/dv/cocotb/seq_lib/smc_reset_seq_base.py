# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for the SMC reset / reset-CSR sequence family.

Every sequence that drives ``rst_cold_ni`` / ``rst_cool_ni`` / ``powergood_i``
and observes the five ``RESET_SAMPLE_FIELDS`` needs the same four primitives, so
they are defined here once instead of being copy-pasted per sequence:

* ``_send`` -- build one ``SmcResetItem``, validate the keyword names, dispatch.
* ``_wait_state`` / ``_wait_released`` -- bounded ``WAIT_STATE`` handshakes
  carrying exact expected levels; expiry raises in the scoreboard with the last
  observed state ([TIMEOUT-MUST-FAIL] / [NO-BLIND-DELAY-SYNC]).
* ``_raw_after`` -- one expectation-carrying snapshot, ``cycles`` ``clk_ref_i``
  edges after the caller's stimulus.
* ``_hold_raw`` -- the same expectations at **every** sample of a window, which
  is what proves "still asserted while the pin is held": a single instantaneous
  sample passes for a DUT that releases the reset anywhere else inside the
  driven hold ([EXACT-EXPECTATION]).

The keyword guard: ``_send`` applies the expectations with ``setattr``, so a
mistyped ``expect_*`` would silently become a non-check instead of a compare
([NO-ALWAYS-PASS-CHECKER]). ``_SEND_KEYS`` is derived from
``RESET_SAMPLE_FIELDS`` so it tracks the item definition, and any keyword
outside it (plus ``expect_left_stable`` / ``timeout_ref_cycles``) raises
([REUSE-AND-LAYERING]).

Sequences whose reset items travel on a *different* sequencer than the one they
were started on (the CSR-across-reset sequences run on the SEP_IN AXI
sequencer) override ``_dispatch_reset_item`` only; they inherit the guard and
every primitive unchanged.

Expected levels are SPEC-derived (``hw/sys/smc/doc/clk_rst.adoc``).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import RESET_SAMPLE_FIELDS, SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class SmcResetSeqBase(smc_base_test_seq):
    """Reset-item primitives + the ``expect_*`` keyword guard, defined once."""

    # Ceilings for the bounded waits, never the checked quantity. Subclasses
    # override with their own SPEC/measurement-derived numbers; the defaults
    # here are the widest of the family (assert bound must exceed
    # smc_reset_ctrl's 32-sample de-glitch window plus the 4-stage output
    # synchronizers, release bound the cold-reset extender).
    ASSERT_BOUND_REF_CYCLES = 400
    RELEASE_BOUND_REF_CYCLES = 2000
    # Default width of a "still asserted" hold window, in clk_ref_i edges: as
    # wide as smc_reset_ctrl's 32-sample de-glitch window, so an incorrect
    # release that took a full de-glitch to become visible is still inside the
    # checked window.
    MID_ASSERT_HOLD_REF_CYCLES = 32

    # The only keyword names `_send` may set on the item. Anything else is a
    # typo, and a typo applied by blind setattr is a silent non-check.
    _SEND_KEYS = frozenset(
        [f"expect_{f}" for f in RESET_SAMPLE_FIELDS] + ["expect_left_stable", "timeout_ref_cycles"]
    )

    def __init__(self, name: str = "smc_reset_seq_base") -> None:
        super().__init__(name)
        # Human-readable record of every bounded/held leg, for the retained log.
        self._timeout_paths: list[str] = []

    # --- dispatch -------------------------------------------------------
    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        """Default: this sequence runs on the reset agent's own sequencer."""
        await self.start_item(item)
        await self.finish_item(item)

    # --- primitives -----------------------------------------------------
    async def _send(
        self,
        op: SmcResetOp,
        *,
        item_name: str | None = None,
        **expects,
    ) -> SmcResetItem:
        bad = set(expects) - self._SEND_KEYS
        assert not bad, f"unknown reset item keyword(s) {sorted(bad)} (typo = silent non-check)"
        item = SmcResetItem(item_name or op.value.lower())
        item.op = op
        for field, value in expects.items():
            setattr(item, field, value)
        await self._dispatch_reset_item(item)
        return item

    async def _wait_state(
        self,
        label: str | None = None,
        *,
        bound: int | None = None,
        item_name: str | None = None,
        **expects,
    ) -> SmcResetItem:
        """Bounded WAIT_STATE handshake on the exact expected reset levels.

        The expectations travel on the item, so a window that never matches
        fails in the scoreboard with the last observed state instead of being
        absorbed here.
        """
        bound = self.ASSERT_BOUND_REF_CYCLES if bound is None else bound
        item = await self._send(
            SmcResetOp.WAIT_STATE,
            item_name=item_name or label,
            timeout_ref_cycles=bound,
            **expects,
        )
        if label:
            self._timeout_paths.append(
                f"{label}: bound={bound} ref_cycles matched at {item.wait_ref_cycles} last={item}"
            )
        return item

    async def _wait_released(
        self,
        label: str | None = None,
        *,
        bound: int | None = None,
    ) -> SmcResetItem:
        """Bounded handshake: all five observables back to released."""
        return await self._wait_state(
            label,
            bound=self.RELEASE_BOUND_REF_CYCLES if bound is None else bound,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=1,
            expect_rst_primary_smc_clk_n=1,
            expect_rst_wdt_smc_clk_n=1,
        )

    async def _raw_after(self, cycles: int, **expects) -> SmcResetItem:
        """One snapshot, `cycles` clk_ref_i edges after the caller's stimulus.

        With no ``expect_*`` this is an OBSERVED-ONLY transition diagnostic (the
        scoreboard books it in a separate counter that cannot satisfy an
        activity floor). Use ``_hold_raw`` -- not this -- to prove a level is
        *held*: one sample cannot see a release that happens at any other
        instant of the driven window.
        """
        await ClockCycles(cocotb.top.clk_ref_i, cycles)
        return await self._send(SmcResetOp.RAW_SAMPLE, **expects)

    async def _hold_raw(
        self,
        label: str,
        *,
        hold: int | None = None,
        **expects,
    ) -> SmcResetItem:
        """Assert `expects` at EVERY sample across a `hold`-wide window.

        Each iteration advances one ``clk_ref_i`` edge *before* sampling, so
        these observations are separated in simulation time from the
        ``WAIT_STATE`` that matched the same levels -- and each RAW_SAMPLE
        carries the expectations, so the scoreboard fails the test the moment
        the DUT leaves the expected state inside the window. Unlike a
        first-match poll (or a single snapshot) this cannot be satisfied by one
        lucky instant.
        """
        hold = self.MID_ASSERT_HOLD_REF_CYCLES if hold is None else hold
        assert expects, (
            f"_hold_raw({label!r}) with no expectation is not a check: every "
            f"sample would be booked OBSERVED-ONLY"
        )
        assert hold >= 1, f"_hold_raw({label!r}) needs a non-empty window"
        last = None
        for _ in range(hold):
            await ClockCycles(cocotb.top.clk_ref_i, 1)
            last = await self._send(SmcResetOp.RAW_SAMPLE, **expects)
        cocotb.log.info(
            "CHK-MID-ASSERT-HOLD: %s stayed in the expected state at all %d "
            "checked clk_ref_i samples after the assert handshake matched; "
            "last %s",
            label,
            hold,
            last,
        )
        self._timeout_paths.append(
            f"{label}: hold={hold} ref_cycles all samples matched last={last}"
        )
        return last
