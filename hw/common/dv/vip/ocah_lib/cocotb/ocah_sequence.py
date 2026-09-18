# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence base: the looped-scenario contract every bench scenario carries.

The base test sets ``scenario_seed`` (runner seed plus pass index),
``random_count``, and ``loop_index`` before ``start()``. Every draw in the pass
comes from ``rng(label)``, a ``random.Random`` seeded from the scenario seed
salted by the label, so the pass is replayable from the simulator seed plus
the pass index. Pattern and salt helpers forward to ``OcahRng``; step and
iteration logging use the shared formats. This is the parent of every
``<dut>_base_test_seq`` virtual sequence and of every VIP master sequence. The
SV-UVM twin is ``ocah_sequence``; it seeds the ``body()`` process once
(``seed_scenario_rng``) where Python hands each helper its own salted RNG.

No evidence handle here: its type is the protocol checker the bench needs, so
the bench base sequence declares it.
"""

from __future__ import annotations

import logging
import random

from pyuvm import uvm_sequence

from .ocah_rng import OcahRng

__all__ = ["OcahSequence", "OcahSequenceError"]


class OcahSequenceError(RuntimeError):
    """Raised when a sequence is used outside the looped-scenario contract."""


class OcahSequence(uvm_sequence):
    """Per-pass seed, loop index, seeded pattern helpers, and step logging."""

    def __init__(
        self,
        name: str = "ocah_sequence",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
        loop_index: int = 0,
    ) -> None:
        super().__init__(name)
        # A child of the `cocotb` logger: the cocotb log configuration raises only
        # that hierarchy to INFO, so a same-named root-child logger keeps the root's
        # WARNING threshold and its INFO records never reach the simulation log.
        # Resolved by name: `cocotb.log` exists only once the simulator has
        # initialised, and this class also runs in the simulator-free selftest.
        self.log = logging.getLogger("cocotb").getChild(name)
        # Per-pass seed: runner seed plus loop index, set by the base test.
        self.scenario_seed = scenario_seed
        # Random patterns or operations per pass.
        self.random_count = random_count
        # Pass index within the looped run (0-based); pass 0 follows bring-up.
        self.loop_index = loop_index

    # ------------------------------------------------------------------
    # Seeded randomness.
    # ------------------------------------------------------------------

    def salted_seed(self, label: str) -> int:
        """Scenario seed salted by a label, for a helper that needs its own stream."""
        if self.scenario_seed is None:
            raise OcahSequenceError(
                f"{self.get_name()} has no scenario_seed; the test sets it before start()"
            )
        return OcahRng.salted_seed(self.scenario_seed, label)

    def rng(self, salt: str = "") -> random.Random:
        """Deterministic RNG for this sequence and label (the sequence name when empty)."""
        label = salt or self.get_name()
        seed = self.salted_seed(label)
        self.log.info("Using deterministic random seed %d for %s", seed, label)
        return random.Random(seed)

    @staticmethod
    def bit_mask(width: int) -> int:
        return OcahRng.bit_mask(width)

    def random_pattern(self, width: int, rng: random.Random) -> int:
        return OcahRng.random_pattern(width, rng)

    def directed_patterns(
        self,
        width: int,
        *,
        rng: random.Random | None = None,
        random_count: int | None = None,
    ) -> list[int]:
        """Directed corners first, ``random_count`` seeded random patterns on top."""
        count = self.random_count if random_count is None else random_count
        return OcahRng.directed_patterns(width, count, rng or self.rng("directed_patterns"))

    # ------------------------------------------------------------------
    # Shared log formats.
    # ------------------------------------------------------------------

    def log_step(self, step: int | str, message: str, *args: object) -> None:
        """Log a numbered verification step."""
        self.log.info("Step %s: " + message, step, *args)

    def log_iteration(self, index: int, total: int, message: str, *args: object) -> None:
        """Log loop iteration context before applying stimulus."""
        self.log.info("Iteration %d/%d: " + message, index, total, *args)
