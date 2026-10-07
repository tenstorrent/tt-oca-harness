# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-disable functional coverage.

The SV covergroups compile only on the commercial simulators, under the
bench's ``ifndef VERILATOR`` guard, so this Python-side ledger records the
per-field gating contract on every simulator: one cell per
``(field, disable_value, outcome)`` tuple, sampled only after the associated
functional checker has passed, so the outcome follows from the disable value:
``(field, 0, allowed)`` and ``(field, 1, blocked)``. Auxiliary bins record mask
classes and the isolation / release-without-replay / recovery evidence.

Each matrix test owns a ledger over the fields it drives, enforces their
cells via ``require_cells`` before completing, and emits a JSON artifact
under its ``coverage/`` directory recording the cells it hit and whether its
fields' cells are all covered.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from .dtp_dbg_disable import DBG_DISABLE_FIELDS, format_dbg_disable

__all__ = ["DtpDbgDisableFcov", "cell_name", "mask_class"]

ALLOWED = "allowed"
BLOCKED = "blocked"

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

    def __init__(self, feature_key: str, fields: tuple[str, ...]) -> None:
        unknown = set(fields) - set(DBG_DISABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown dbg_disable field(s) {sorted(unknown)}")
        self.feature_key = feature_key
        self.fields = fields
        self.cells: Counter[tuple[str, int, str]] = Counter()
        self.mask_classes: Counter[str] = Counter()
        self.aux: Counter[str] = Counter()
        self.log = logging.getLogger(f"dtp_fcov.{feature_key}")

    def sample_cell(
        self,
        field: str,
        disable_value: int,
        *,
        mask: Mapping[str, int],
        operation: str,
        result: str,
    ) -> None:
        """Record the cell of a checker-verified operation under ``field = disable_value``."""
        if field not in self.fields:
            raise ValueError(f"{self.feature_key} does not cover dbg_disable field {field!r}")
        value = int(disable_value) & 1
        outcome = BLOCKED if value else ALLOWED
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

    def required_cells(self) -> tuple[tuple[str, int, str], ...]:
        """Both cells of every field this ledger covers."""
        return tuple(
            (field, value, outcome)
            for field in self.fields
            for value, outcome in ((0, ALLOWED), (1, BLOCKED))
        )

    def require_cells(self) -> None:
        """Fail the test unless every required cell was hit."""
        missing = [cell_name(*cell) for cell in self.required_cells() if cell not in self.cells]
        if missing:
            raise AssertionError(f"{self.feature_key}: uncovered cells: {missing}")

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
            "required_cells": [cell_name(*cell) for cell in self.required_cells()],
            "cells_hit": hit,
            "cell_counts": {cell_name(*cell): count for cell, count in sorted(self.cells.items())},
            "mask_classes": dict(self.mask_classes),
            "aux_bins": dict(self.aux),
            "satisfied": set(self.required_cells()) <= set(self.cells),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        self.log.info("FCOV artifact written: %s (%d cells hit)", path, len(hit))
        return path
