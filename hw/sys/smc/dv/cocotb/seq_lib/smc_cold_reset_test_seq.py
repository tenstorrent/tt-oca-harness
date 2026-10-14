# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_cold_reset_test (SMC_001).

Exercises the SmcResetAgent + SmcClkAgent observations of plan card SMC_001:
clock edges, bring-up levels, cold assert, powergood gate, cool primary, and
the POR/cool interaction fences.

Synchronization and verdicts:

* every reset step is a bounded ``WAIT_STATE`` handshake carrying the exact
  expected levels, so the scoreboard owns the verdict and expiry raises with the
  last observed state ([TIMEOUT-MUST-FAIL]). There is no fixed settle on the
  proof path -- recovery is a wait for the released levels, not a delay
  ([NO-BLIND-DELAY-SYNC]).
* the POR/cold interaction fence (S7) is a *hold* monitor, not a first-match
  poll: with ``powergood_stable_o==0`` every sample across a window wider than
  the DUT's 32-sample cold de-glitch must still show the cold-stable and primary
  resets asserted. A delayed incorrect release inside the window fails, which a
  return-on-first-match poll could not see ([NO-ALWAYS-PASS-CHECKER]).
* the non-vacuity fence (S9) counts the scoreboard's *fail-capable* reset
  checks (``reset_samples_seen`` + ``reset_raw_checks_seen`` +
  ``reset_wait_checks_seen``) at every step boundary and requires each of
  S3..S8 to have advanced that total **with checks of its own**: the shared
  ``_recover_sample()`` tail's contribution is tracked separately and
  subtracted, so a step is not credited for the recovery every step ends with
  and dropping that step's own assert leg fails the fence. Expectation-free
  ``RAW_SAMPLE`` observations are booked in a separate counter and
  cannot satisfy it either, so a step whose expectations were dropped (or which
  never ran) fails instead of being papered over ([NO-ZERO-ACTIVITY-PASS] /
  [NO-DUMMY-DEAD-CODE]).

Expected levels are SPEC-derived (``hw/sys/smc/doc/clk_rst.adoc``): POR holds the
SMC functional reset gated until power-good is stable, cold reset drives the
cold-stable and primary paths, and cool reset is a primary-level reset that
leaves the cold-stable path released.
"""

from __future__ import annotations

import cocotb
from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from ._one_shot import _OneShot
from .smc_reset_seq_base import SmcResetSeqBase


class smc_cold_reset_test_seq(SmcResetSeqBase):
    """SMC_001 cold-reset / POR / cool path with exact CHK evidence lines."""

    CLK_WINDOW_REF_CYCLES = 64
    # Bounds (ceilings for the handshakes, never the checked quantity): the
    # assert bound must exceed the 32-sample cold/cool de-glitch window plus the
    # 4-stage output synchronizers, the recovery bound the cold-reset extender.
    ASSERT_BOUND_REF_CYCLES = 200
    RELEASE_BOUND_REF_CYCLES = 700
    # POR fence hold window: 2x the DUT's 32-sample cold de-glitch, so a cold
    # path that (incorrectly) qualified while power-good is not stable would
    # have been observed inside it.
    POR_HOLD_REF_CYCLES = 64
    # Steps whose stimulus must have produced at least one fail-capable reset
    # check *of their own* in the scoreboard. S1 (prose SETUP) and S2 (TB-driven
    # input clock counts, explicitly not DUT proof) issue no reset expectations,
    # so claiming them here would put a by-construction term into the fence.
    NONVAC_STEPS = ("S3", "S4", "S5", "S6", "S7", "S8")

    def __init__(self, name: str = "smc_cold_reset_test_seq") -> None:
        super().__init__(name)
        self.sample = None
        # (step id, fail-capable reset checks the scoreboard had booked when the
        # step started, checks booked by the shared recovery tail so far). The
        # per-step delta of the first minus the delta of the second -- i.e. only
        # what the step's own legs produced -- is the fence in S9.
        self._step_marks: list[tuple[str, int, int]] = []
        # Checks booked inside `_recover_sample`. They belong to the shared
        # recovery tail every step ends with, not to the step's own assert leg,
        # so they are excluded from the per-step non-vacuity delta below.
        self._recovery_checks = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _checked_reset_evidence(self) -> int:
        """Scoreboard reset checks that can FAIL, i.e. real evidence so far.

        Excludes ``reset_raw_observations_seen``: an
        expectation-free snapshot is booked OBSERVED-ONLY and must not be able
        to satisfy a non-vacuity fence.
        """
        sb = self.env.scoreboard
        return sb.reset_samples_seen + sb.reset_raw_checks_seen + sb.reset_wait_checks_seen

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_marks.append((step_id, self._checked_reset_evidence(), self._recovery_checks))
        self._log(f"STEP {step_id}: {detail}")

    async def _recover_sample(self) -> SmcResetItem:
        """Wait (bounded) for the released levels, then take the SAMPLE.

        Every scenario step ends with this shared tail, so the checks it books
        are attributed to ``_recovery_checks`` and subtracted from the per-step
        non-vacuity delta in S9: otherwise every step would be credited with
        this tail's >=2 checks and the fence could not tell that a step's own
        assert leg had stopped checking anything ([NO-DUMMY-DEAD-CODE]).
        """
        before = self._checked_reset_evidence()
        await self._wait_released("RECOVER_RELEASED")
        item = await self._send(SmcResetOp.SAMPLE)
        self.sample = item
        self._recovery_checks += self._checked_reset_evidence() - before
        return item

    async def _count_clocks(self) -> SmcClkItem:
        item = SmcClkItem("count_window")
        item.op = SmcClkOp.COUNT_EDGES
        item.window_ref_cycles = self.CLK_WINDOW_REF_CYCLES
        await _OneShot(item, "clk_edges_os").start(self.env.clk_agent.sequencer)
        return item

    async def body(self) -> None:
        # S1 — SETUP (bring-up already done by smc_base_test; restate levels)
        self._mark_step(
            "S1",
            "SETUP clocks running; powergood_i=1 rst_cold_ni=1 rst_cool_ni=1 (post base bring-up)",
        )

        # S2 — clock edges. clk_smc_i / clk_ref_i / clk_periph_i are DUT *inputs*
        # driven by cocotb Clock(...) in smc_base_test._bring_up, so these counts
        # can only fail on a TB clock-generator mistake, never on wrong DUT RTL.
        # They are a SETUP self-check and NOT emitted as DUT
        # evidence ([NO-ALWAYS-PASS-CHECKER]); the DUT-side gated-clock proof
        # lives in the smc clk/cg tests.
        self._mark_step("S2", "COUNT_EDGES on clk_smc_i/clk_ref_i/clk_periph_i")
        clk = await self._count_clocks()
        assert clk.smc_rising_edges >= 1, f"clk_smc edges={clk.smc_rising_edges}"
        assert clk.ref_rising_edges >= 1, f"clk_ref edges={clk.ref_rising_edges}"
        assert clk.periph_rising_edges >= 1, f"clk_periph edges={clk.periph_rising_edges}"
        self._log(
            "SETUP-CLK-EDGES (TB-driven input clocks -- NOT DUT proof): in a "
            f"fixed window rising_edges(clk_smc_i)={clk.smc_rising_edges}>=1 AND "
            f"rising_edges(clk_ref_i)={clk.ref_rising_edges}>=1 AND "
            f"rising_edges(clk_periph_i)={clk.periph_rising_edges}>=1"
        )

        # S3 — bring-up SAMPLE
        self._mark_step("S3", "SAMPLE post-bring-up levels")
        s3 = await self._send(SmcResetOp.SAMPLE)
        self.sample = s3
        assert s3.resolvable and s3.powergood_stable == 1
        assert s3.rst_cold_stable_ref_clk_n == 1
        assert s3.rst_primary_ref_clk_n == 1
        assert s3.rst_primary_smc_clk_n == 1
        self._log(
            "CHK-BRINGUP-LEVELS: after bring-up settle SAMPLE: "
            f"powergood_stable_o=={s3.powergood_stable} AND "
            f"rst_cold_stable_ref_clk_no=={s3.rst_cold_stable_ref_clk_n} AND "
            f"rst_primary_ref_clk_no=={s3.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={s3.rst_primary_smc_clk_n}"
        )

        # S4 — cold assert (lifecycle: set → observed → cleared → checked_cleared)
        self._mark_step("S4", "COLD_RST_LO then wait primary asserted")
        await self._send(SmcResetOp.COLD_RST_LO)
        self._log("LIFECYCLE CHK-COLD-ASSERT-PRIMARY set: COLD_RST_LO drives rst_cold_ni=0")
        s4 = await self._wait_state(
            "COLD_ASSERT_PRIMARY",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._log(
            "LIFECYCLE CHK-COLD-ASSERT-PRIMARY observed: "
            f"rst_primary_ref_clk_no=={s4.rst_primary_ref_clk_n}; "
            f"rst_primary_smc_clk_no=={s4.rst_primary_smc_clk_n}"
        )
        self._log(
            "CHK-COLD-ASSERT-PRIMARY: after rst_cold_ni=0, within bound SAMPLE: "
            f"rst_primary_ref_clk_no=={s4.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={s4.rst_primary_smc_clk_n}"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        self._log("LIFECYCLE CHK-COLD-ASSERT-PRIMARY cleared: COLD_RST_HI restores rst_cold_ni=1")
        s4c = await self._recover_sample()
        assert s4c.rst_primary_ref_clk_n == 1 and s4c.rst_primary_smc_clk_n == 1, s4c
        self._log(
            "LIFECYCLE CHK-COLD-ASSERT-PRIMARY checked_cleared: SAMPLE "
            f"rst_primary_ref_clk_no=={s4c.rst_primary_ref_clk_n} "
            f"rst_primary_smc_clk_no=={s4c.rst_primary_smc_clk_n}"
        )

        # S5 — powergood gates cold path
        self._mark_step("S5", "POWERGOOD_LO then wait powergood_stable_o==0")
        await self._send(SmcResetOp.POWERGOOD_LO)
        self._log("LIFECYCLE CHK-POWERGOOD-GATES set: POWERGOOD_LO drives powergood_i=0")
        s5 = await self._wait_state(
            "POWERGOOD_GATES",
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._log(
            f"LIFECYCLE CHK-POWERGOOD-GATES observed: powergood_stable_o=={s5.powergood_stable}"
        )
        self._log(
            "CHK-POWERGOOD-GATES: after powergood_i=0, within bound SAMPLE: "
            f"powergood_stable_o=={s5.powergood_stable} AND (POR gates the "
            f"functional reset path) rst_cold_stable_ref_clk_no=="
            f"{s5.rst_cold_stable_ref_clk_n} AND rst_primary_ref_clk_no=="
            f"{s5.rst_primary_ref_clk_n} AND rst_primary_smc_clk_no=="
            f"{s5.rst_primary_smc_clk_n}"
        )
        await self._send(SmcResetOp.POWERGOOD_HI)
        self._log("LIFECYCLE CHK-POWERGOOD-GATES cleared: POWERGOOD_HI restores powergood_i=1")
        s5c = await self._recover_sample()
        assert s5c.powergood_stable == 1, s5c
        self._log(
            "LIFECYCLE CHK-POWERGOOD-GATES checked_cleared: SAMPLE "
            f"powergood_stable_o=={s5c.powergood_stable}"
        )

        # S6 — cool assert / release
        self._mark_step("S6", "COOL_RST_LO/HI primary assert/release")
        await self._send(SmcResetOp.COOL_RST_LO)
        self._log("LIFECYCLE CHK-COOL-PRIMARY set: COOL_RST_LO drives rst_cool_ni=0")
        s6a = await self._wait_state(
            "COOL_ASSERT_PRIMARY",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._log(
            "LIFECYCLE CHK-COOL-PRIMARY observed: "
            f"rst_primary_ref_clk_no=={s6a.rst_primary_ref_clk_n}; "
            f"rst_primary_smc_clk_no=={s6a.rst_primary_smc_clk_n}"
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        self._log("LIFECYCLE CHK-COOL-PRIMARY cleared: COOL_RST_HI drives rst_cool_ni=1")
        s6b = await self._wait_state(
            "COOL_RELEASE_PRIMARY",
            bound=self.RELEASE_BOUND_REF_CYCLES,
            expect_rst_primary_ref_clk_n=1,
            expect_rst_primary_smc_clk_n=1,
        )
        self._log(
            "LIFECYCLE CHK-COOL-PRIMARY checked_cleared: SAMPLE "
            f"rst_primary_ref_clk_no=={s6b.rst_primary_ref_clk_n} "
            f"rst_primary_smc_clk_no=={s6b.rst_primary_smc_clk_n}"
        )
        self._log(
            "CHK-COOL-PRIMARY: after rst_cool_ni=0, within bound SAMPLE "
            f"rst_primary_ref_clk_no=={s6a.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={s6a.rst_primary_smc_clk_n}; "
            f"after rst_cool_ni=1, within bound SAMPLE both "
            f"==({s6b.rst_primary_ref_clk_n},{s6b.rst_primary_smc_clk_n})"
        )
        await self._recover_sample()

        # S7 — INT-POR-QUALIFIES-COLD-RESET
        self._mark_step("S7", "POR qualifies cold reset joint observation")
        await self._send(SmcResetOp.POWERGOOD_LO)
        pg0 = await self._wait_state(
            "INT_POR_PG0",
            expect_powergood_stable=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COLD_RST_LO)
        # Hold monitor (fail_on: the cold path releases primary at ANY sample
        # while powergood_stable_o==0). The window is wider than the DUT's
        # 32-sample cold de-glitch, so a cold reset that qualified while POR is
        # not stable would be caught here rather than missed by a
        # return-on-first-match poll.
        cold_while_pg0 = await self._hold_raw(
            "INT_POR_COLD_WHILE_PG0",
            hold=self.POR_HOLD_REF_CYCLES,
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._send(SmcResetOp.POWERGOOD_HI)
        await self._recover_sample()
        await self._send(SmcResetOp.COLD_RST_LO)
        cold_while_pg1 = await self._wait_state(
            "INT_POR_COLD_WHILE_PG1",
            expect_powergood_stable=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._log(
            "CHK-INT-POR-COLD: ordered joint: (1) with powergood_stable_o=="
            f"{pg0.powergood_stable}, COLD_RST_LO leaves the functional reset "
            f"path gated at EVERY one of {self.POR_HOLD_REF_CYCLES} ref-clock "
            "samples (rst_cold_stable_ref_clk_no=="
            f"{cold_while_pg0.rst_cold_stable_ref_clk_n} AND "
            f"rst_primary_ref_clk_no=={cold_while_pg0.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={cold_while_pg0.rst_primary_smc_clk_n}); "
            f"(2) after powergood_stable_o=={cold_while_pg1.powergood_stable} and "
            f"COLD_RST_LO, both primary samples "
            f"==({cold_while_pg1.rst_primary_ref_clk_n},{cold_while_pg1.rst_primary_smc_clk_n})"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._recover_sample()

        # S8 — INT-COOL-PIN-TO-RESET-SEQUENCE
        self._mark_step("S8", "cool pin reset sequence joint observation")
        await self._send(SmcResetOp.COOL_RST_LO)
        cool_lo = await self._wait_state(
            "INT_COOL_LO",
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        cool_hi = await self._wait_state(
            "INT_COOL_HI",
            bound=self.RELEASE_BOUND_REF_CYCLES,
            expect_rst_primary_ref_clk_n=1,
            expect_rst_primary_smc_clk_n=1,
        )
        self._log(
            "CHK-INT-COOL-SEQ: ordered joint: COOL_RST_LO then SAMPLE "
            f"rst_primary_ref_clk_no=={cool_lo.rst_primary_ref_clk_n} and "
            f"rst_primary_smc_clk_no=={cool_lo.rst_primary_smc_clk_n} within bound; "
            f"COOL_RST_HI then SAMPLE both "
            f"==({cool_hi.rst_primary_ref_clk_n},{cool_hi.rst_primary_smc_clk_n}) within bound"
        )
        await self._recover_sample()

        # S9 TIMEOUT bookkeeping + NONVAC fence
        self._mark_step("S9", "TIMEOUT path bookkeeping")
        # Non-vacuity: every step in NONVAC_STEPS must contribute at least one
        # fail-capable reset check of its own, measured on the scoreboard
        # counters at the step boundaries. The shared `_recover_sample()` tail
        # books checks of its own at the end of every step, so its contribution
        # is subtracted; a step that carries no expectations, or never reaches
        # the DUT, then contributes 0 and fails here.
        deltas: list[str] = []
        for (sid, before, rec_before), (_nxt, after, rec_after) in zip(
            self._step_marks, self._step_marks[1:]
        ):
            if sid not in self.NONVAC_STEPS:
                continue
            own = (after - before) - (rec_after - rec_before)
            assert own > 0, (
                f"step {sid} produced no fail-capable reset check of its own: "
                f"the scoreboard's checked-evidence count advanced by "
                f"{after - before} across it, all of it booked by the shared "
                f"recovery tail ({rec_after - rec_before}); an OBSERVED-ONLY "
                f"snapshot does not count either"
            )
            deltas.append(f"{sid}:+{own}")
        self._log(
            "CHK-NONVAC: every scenario step advanced the scoreboard's "
            "fail-capable reset-check count with checks of its own, i.e. "
            "excluding the shared recovery tail ("
            + " ".join(deltas)
            + f"), total {self._checked_reset_evidence()} checks of which "
            f"{self._recovery_checks} were booked by the recovery tail; "
            "expectation-free snapshots excluded"
        )
        for line in self._timeout_paths:
            self._log(f"CHK-TIMEOUT-PATHS: {line}")
        # Activity gate: the CHK lines above are only evidence because the
        # scoreboard actually compared these legs ([NO-ZERO-ACTIVITY-PASS]).
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= 12, (
            f"expected at least 12 bounded reset WAIT_STATE checks, scoreboard "
            f"saw {sb.reset_wait_checks_seen}"
        )
        assert sb.reset_raw_checks_seen >= self.POR_HOLD_REF_CYCLES, (
            f"expected {self.POR_HOLD_REF_CYCLES} checked POR-fence hold "
            f"samples, scoreboard saw {sb.reset_raw_checks_seen}"
        )
        self._log("SMC_001 scenario PASS")
