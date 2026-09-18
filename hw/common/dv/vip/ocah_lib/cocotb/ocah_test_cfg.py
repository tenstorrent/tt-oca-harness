# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test configuration base: the highest configuration level and the only object the seed touches.

A bench's ``<Dut>TestCfg`` adds the fields worth randomizing (timing, sizes,
modes), the knob-derived controls, the features the scoreboard must compare,
and the scenario evidence policy; the base test fills ``seed`` and
``random_count`` from the knob accessor, then randomizes it once. The env cfg
is derived from this object and is what the env reads. The SV-UVM twin is
``ocah_test_cfg``.
"""

from __future__ import annotations

from pyuvm import uvm_object

__all__ = ["OcahTestCfg"]


class OcahTestCfg(uvm_object):
    """Seed, random count, and the scoreboard features a run must compare."""

    def __init__(self, name: str = "ocah_test_cfg") -> None:
        super().__init__(name)
        # Runner seed (``RANDOM_SEED``, read once by ``OcahTest.base_seed``).
        self.seed: int = 1
        # Random patterns or operations per scenario pass.
        self.random_count: int = 5
        # Scoreboard features that must record at least one comparison and
        # no mismatch for the run to pass (``<Dut>Scoreboard`` feature names).
        self.required_features: list[str] = []

    def require_feature(self, feature: str) -> None:
        """Add a feature to the required set; a repeat is a no-op."""
        if feature not in self.required_features:
            self.required_features.append(feature)

    def __str__(self) -> str:
        return (
            f"seed={self.seed} random_count={self.random_count} "
            f"required_features={self.required_features}"
        )
