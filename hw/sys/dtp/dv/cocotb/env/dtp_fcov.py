# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-disable functional coverage.

Verilator cannot compile SV covergroups, so this Python-side ledger records
the per-field gating contract instead: one cell per
``(field, disable_value, observed_outcome)`` tuple, sampled only after the
associated functional checker has passed. The legal cells are
``(field, 0, allowed)`` and ``(field, 1, blocked)`` for each of the eleven
``dbg_disable_t`` fields — 22 cells total; a contradictory outcome is a
checker failure, never a coverage bin. Auxiliary bins record mask classes and
the isolation / release-without-replay / recovery evidence.

Each matrix test enforces its own required cells via ``require_cells``
before completing, and emits a JSON artifact under its ``coverage/``
directory recording the cells it hit.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from env.dtp_dbg_disable import DBG_DISABLE_FIELDS, format_dbg_disable

ALLOWED = "allowed"
BLOCKED = "blocked"

REQUIRED_CELLS: tuple[tuple[str, int, str], ...] = tuple(
    (field, value, outcome)
    for field in DBG_DISABLE_FIELDS
    for value, outcome in ((0, ALLOWED), (1, BLOCKED))
)

MASK_CLASSES = ("all_clear", "one_hot", "multi_hot", "all_disabled")
AUX_BINS = ("unrelated_isolation", "release_no_replay", "recovery")


def cell_name(field: str, value: int, outcome: str) -> str:
    return f"{field}:{value}:{outcome}"


def mask_class(mask: Mapping[str, int]) -> str:
    """Classify a named disable mask over the fields it provides."""
    values = [int(v) & 1 for v in mask.values()]
    count = sum(values)
    if count == 0:
        return "all_clear"
    if count == 1:
        return "one_hot"
    if count == len(values):
        return "all_disabled"
    return "multi_hot"


class DtpDbgDisableFcov:
    """Checker-gated coverage ledger for the debug-disable contract."""

    def __init__(self, feature_key: str) -> None:
        self.feature_key = feature_key
        self.cells: Counter[tuple[str, int, str]] = Counter()
        self.mask_classes: Counter[str] = Counter()
        self.aux: Counter[str] = Counter()
        self.log = logging.getLogger(f"dtp_fcov.{feature_key}")

    def sample_cell(
        self,
        field: str,
        disable_value: int,
        outcome: str,
        *,
        mask: Mapping[str, int],
        operation: str,
        result: str,
    ) -> None:
        """Record one checker-verified (field, value, outcome) cell."""
        if field not in DBG_DISABLE_FIELDS:
            raise ValueError(f"unknown dbg_disable field {field!r}")
        if outcome not in (ALLOWED, BLOCKED):
            raise ValueError(f"unknown outcome {outcome!r}")
        value = int(disable_value) & 1
        expected = BLOCKED if value else ALLOWED
        assert outcome == expected, (
            f"contradictory gating outcome for {field}: disable={value} but "
            f"outcome={outcome} (operation={operation}, result={result}) — "
            f"this is a checker failure, not a coverage bin"
        )
        self.cells[(field, value, outcome)] += 1
        self.log.info(
            "FCOV cell field=%s disable=%d outcome=%s mask=[%s] op=%s result=%s",
            field,
            value,
            outcome,
            format_dbg_disable(mask),
            operation,
            result,
        )

    def sample_mask(self, mask: Mapping[str, int]) -> None:
        cls = mask_class(mask)
        self.mask_classes[cls] += 1
        self.log.info("FCOV mask class=%s mask=[%s]", cls, format_dbg_disable(mask))

    def sample_aux(self, name: str, *, context: str) -> None:
        if name not in AUX_BINS:
            raise ValueError(f"unknown auxiliary bin {name!r}")
        self.aux[name] += 1
        self.log.info("FCOV aux bin=%s context=%s", name, context)

    def hit_cells(self) -> set[tuple[str, int, str]]:
        return set(self.cells)

    def require_cells(self, fields: tuple[str, ...]) -> None:
        """Assert every legal cell for the given fields was hit in this test."""
        missing = [
            cell_name(field, value, outcome)
            for field in fields
            for value, outcome in ((0, ALLOWED), (1, BLOCKED))
            if (field, value, outcome) not in self.cells
        ]
        assert not missing, f"{self.feature_key}: uncovered cells: {missing}"

    def _coverage_dir(self) -> Path:
        results = os.environ.get("COCOTB_RESULTS_FILE")
        base = Path(results).resolve().parent if results else Path.cwd()
        return base / "coverage"

    def write_artifact(self, *, seed: int) -> Path:
        """Emit the JSON coverage artifact recording the cells this run hit."""
        out_dir = self._coverage_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"dbg_disable_fcov_{self.feature_key}.json"
        hit = sorted(cell_name(*cell) for cell in self.cells)
        payload = {
            "artifact_type": "dbg_disable_fcov",
            "feature_key": self.feature_key,
            "method": "python_fcov_ledger",
            "seed": seed,
            "required_cells": [cell_name(*cell) for cell in REQUIRED_CELLS],
            "cells_hit": hit,
            "cell_counts": {cell_name(*cell): count for cell, count in sorted(self.cells.items())},
            "mask_classes": dict(self.mask_classes),
            "aux_bins": dict(self.aux),
            "satisfied": set(REQUIRED_CELLS) <= set(self.cells),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        self.log.info("FCOV artifact written: %s (%d cells hit)", path, len(hit))
        return path
