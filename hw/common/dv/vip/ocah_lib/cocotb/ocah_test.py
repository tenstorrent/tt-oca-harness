# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test base: the knob accessor, the seed, the looped-scenario runner, and the verdict contract.

The run verdict is cocotb's: an exception escaping a phase fails the test, so
the scoreboard and the checkers raise through ``OcahChecker.finalize`` and no
test code prints a pass banner. The SV-UVM twin ``ocah_test`` emits
``UVM TEST PASSED`` from ``report_phase`` for the uvm-log parser instead. This
is the one accessor of the runner seed (``RANDOM_SEED``, exported by the
runner from ``--seed``).

Looped-scenario contract, shared with the SV twin: every looped scenario runs
at least ``MIN_DEFAULT_LOOPS`` passes, each with its own scenario seed (runner
seed plus loop index), so directed scenarios re-prove back-to-back recovery
and randomized scenarios add stimulus diversity. Loop counts resolve from
knobs without touching test code: the per-test knob, then the group knob,
then the suite knob, then the default; the random-count knob sets the random
patterns per pass (default 5). A bench base test implements the hooks: build
its cfgs and env in ``build_phase``, walk the reset ladder in ``bring_up()``,
name its sequencer in ``scenario_sequencer()``, and plumb the scenario
sequence in ``plumb_scenario_seq()``. A thin scenario test either overrides
``create_scenario_seq()`` and the knob-name hooks and inherits ``run_phase()``,
or calls ``start_looped_seq()`` with its sequence class: the Python form of
the same contract, since a class is a value here.
"""

from __future__ import annotations

import os
from typing import Any

from pyuvm import uvm_sequencer, uvm_test

from .ocah_knobs import OcahKnobs
from .ocah_sequence import OcahSequence

__all__ = ["OcahTest", "OcahTestError"]

_SEED_ENV = "RANDOM_SEED"


class OcahTestError(RuntimeError):
    """Raised when a bench leaves a looped-scenario hook unimplemented."""


class OcahTest(uvm_test):
    """Seed and knob accessors, loop policy, looped-scenario runner."""

    # Every looped scenario runs at least this many passes by default.
    MIN_DEFAULT_LOOPS = 16
    # Random patterns or operations per pass when no knob is bound.
    DEFAULT_RANDOM_COUNT = 5

    # ------------------------------------------------------------------
    # Seed and knobs.
    # ------------------------------------------------------------------

    @staticmethod
    def base_seed() -> int:
        """Runner-provided seed; the only read of the seed variable."""
        return int(os.environ.get(_SEED_ENV, "1"), 0)

    def suite_loops_knob(self) -> str:
        """Knob name the bench binds for the suite-wide loop count; empty skips the level."""
        return ""

    def random_count_knob(self) -> str:
        return ""

    def specific_loops_knob(self) -> str:
        return ""

    def group_loops_knob(self) -> str:
        return ""

    def default_loops(self) -> int:
        return self.MIN_DEFAULT_LOOPS

    def random_count(self) -> int:
        """Random patterns or operations per pass."""
        knob = self.random_count_knob()
        if not knob:
            return self.DEFAULT_RANDOM_COUNT
        return OcahKnobs.get_int_min(knob, self.DEFAULT_RANDOM_COUNT, 1)

    def loop_count(
        self,
        specific_knob: str,
        group_knob: str,
        default_count: int = MIN_DEFAULT_LOOPS,
    ) -> int:
        """Loop-count resolution: specific, then group, then suite knob, then the default.

        The default is floored at ``MIN_DEFAULT_LOOPS``; an explicit 0 is a
        configuration defect.
        """
        for knob in (specific_knob, group_knob, self.suite_loops_knob()):
            if knob and OcahKnobs.has_value(knob):
                return OcahKnobs.get_int_min(knob, self.MIN_DEFAULT_LOOPS, 1)
        return max(default_count, self.MIN_DEFAULT_LOOPS)

    # ------------------------------------------------------------------
    # Looped-scenario hooks.
    # ------------------------------------------------------------------

    def create_scenario_seq(self) -> OcahSequence | None:
        """Build one pass's scenario sequence, unconfigured."""
        return None

    def scenario_sequencer(self) -> uvm_sequencer | None:
        """The bench sequencer every scenario pass starts on."""
        return None

    def plumb_scenario_seq(self, seq: OcahSequence) -> None:
        """Hand a scenario pass the handles it needs (cfg, TB interface, evidence)."""

    async def bring_up(self) -> None:
        """Clock and reset bring-up through the bench TB interface; runs once before the first pass."""

    def pre_scenario_pass(self, idx: int) -> None:
        """Per-pass preparation before the scenario is plumbed and started."""

    # ------------------------------------------------------------------
    # Looped-scenario runner.
    # ------------------------------------------------------------------

    async def start_seq(self, seq: OcahSequence, *, sequencer: uvm_sequencer | None = None) -> None:
        """Plumb one sequence and start it on the scenario sequencer (or the one given).

        A sequence started without a scenario seed takes the runner seed.
        """
        if seq.scenario_seed is None:
            seq.scenario_seed = self.base_seed()
        seqr = sequencer if sequencer is not None else self.scenario_sequencer()
        if seqr is None:
            raise OcahTestError("scenario_sequencer() returned None")
        self.plumb_scenario_seq(seq)
        await seq.start(seqr)

    async def start_looped_seq(
        self,
        seq_cls: type[OcahSequence],
        base_name: str,
        *,
        specific_knob: str,
        default_loops: int = MIN_DEFAULT_LOOPS,
        group_knob: str | None = None,
        sequencer: uvm_sequencer | None = None,
        **seq_kwargs: Any,
    ) -> list[OcahSequence]:
        """Run ``seq_cls`` once per pass with deterministic per-pass seeds; returns the passes.

        ``seq_cls`` takes the ``OcahSequence`` keyword arguments plus
        ``seq_kwargs``. ``group_knob`` defaults to ``group_loops_knob()``.
        Bring-up is the caller's: ``run_phase`` has walked it already.
        """
        group = self.group_loops_knob() if group_knob is None else group_knob
        loops = self.loop_count(specific_knob, group, default_loops)
        seed = self.base_seed()
        rcount = self.random_count()
        sequences: list[OcahSequence] = []
        for idx in range(loops):
            seq = seq_cls(
                f"{base_name}_{idx}",
                scenario_seed=seed + idx,
                random_count=rcount,
                **seq_kwargs,
            )
            seq.loop_index = idx
            self.pre_scenario_pass(idx)
            self._log_pass(seq, idx, loops)
            await self.start_seq(seq, sequencer=sequencer)
            sequences.append(seq)
        return sequences

    async def run_looped_scenario(self) -> None:
        """Bring up once, then run ``create_scenario_seq()`` once per pass."""
        loops = self.loop_count(
            self.specific_loops_knob(), self.group_loops_knob(), self.default_loops()
        )
        seed = self.base_seed()
        rcount = self.random_count()
        await self.bring_up()
        for idx in range(loops):
            seq = self.create_scenario_seq()
            if seq is None:
                raise OcahTestError(
                    "looped test must override create_scenario_seq() (or run_phase())"
                )
            seq.scenario_seed = seed + idx
            seq.random_count = rcount
            seq.loop_index = idx
            self.pre_scenario_pass(idx)
            self._log_pass(seq, idx, loops)
            await self.start_seq(seq)

    async def run_phase(self) -> None:
        """Default run flow for looped tests; bespoke tests override it."""
        # Objections belong to tests: this is the test base every
        # <dut>_base_test extends, so the objection pair lives here once.
        self.raise_objection()
        await self.run_looped_scenario()
        self.drop_objection()

    def _log_pass(self, seq: OcahSequence, idx: int, loops: int) -> None:
        self.logger.info(
            "scenario pass %d/%d: %s scenario_seed=%d random_count=%d",
            idx + 1,
            loops,
            seq.get_type_name(),
            seq.scenario_seed,
            seq.random_count,
        )
