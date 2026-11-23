# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-coverage closure for seeded SEP ROM leaves that each grade one cell.

A leaf whose every check passed writes one ``functional-coverage-report.json``
beside its results, naming the single cell it hit. The ``merge`` command unions
the cells of every artifact under a run directory and closes the feature only
when the union holds every required cell. A leaf that fails writes nothing, so a
green regression that missed a cell does not close.

Usage (no simulator needed):
    python3 sep_rom_functional_coverage.py merge <run-dir> --feature <feature-key>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

REPORT_NAME = "functional-coverage-report.json"
_KEYS = ("feature_key", "seed", "required_cells", "cells_hit", "measurements", "satisfied")
# The runner's per-attempt record; a hit beside a non-PASS record is a broken leaf.
_LEAF_RESULT = "result.json"


def result_dir() -> Path:
    """The leaf's results directory: the one holding cocotb's results.xml, else the CWD."""
    results = os.environ.get("COCOTB_RESULTS_FILE")
    return Path(results).resolve().parent if results else Path.cwd()


def write_feature_cell(
    feature_key: str,
    required_cells: Iterable[str],
    hit_cell: str,
    measurements: Mapping[str, object],
    *,
    seed: int,
    out_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Write this leaf's one hit cell for ``feature_key`` and return the artifact path."""
    required = sorted(set(required_cells))
    if not required or not all(isinstance(c, str) and c for c in required):
        raise ValueError(f"required_cells must be non-empty cell names, got {required!r}")
    if not isinstance(hit_cell, str):
        raise ValueError(
            f"one artifact records exactly one cell; got {hit_cell!r}. Write one artifact per leaf"
        )
    if hit_cell not in required:
        raise ValueError(f"hit cell {hit_cell!r} is not one of the required cells {required}")
    report = {
        "feature_key": feature_key,
        "seed": int(seed),
        "required_cells": required,
        "cells_hit": [hit_cell],
        "measurements": dict(measurements),
        "satisfied": required == [hit_cell],
    }
    directory = Path(out_dir) if out_dir is not None else result_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_NAME
    tmp = path.with_name(f".{REPORT_NAME}.{os.getpid()}")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)
    return path


def _leaf_result_error(path: Path, seed: object) -> str | None:
    # The runner writes result.json in the attempt directory, the parent of results/.
    for directory in (path.parent, path.parent.parent):
        record = directory / _LEAF_RESULT
        if not record.is_file():
            continue
        try:
            data = json.loads(record.read_text())
        except (OSError, ValueError) as exc:
            return f"{path}: cannot read the leaf record {record}: {exc}"
        if data.get("status") != "PASS":
            return (
                f"{path}: written by a leaf whose record {record} says "
                f"status={data.get('status')!r}; a failing leaf must not write a hit"
            )
        if "seed" in data and data["seed"] != seed:
            return f"{path}: seed {seed!r} does not match {record} seed {data['seed']!r}"
        return None
    return None


def _check_artifact(path: Path, report: object) -> str | None:
    if not isinstance(report, dict) or any(k not in report for k in _KEYS):
        return f"{path}: not a coverage artifact; it must carry the keys {list(_KEYS)}"
    required, hits = report["required_cells"], report["cells_hit"]
    if not isinstance(required, list) or not required:
        return f"{path}: required_cells must be a non-empty list"
    if not isinstance(hits, list) or len(hits) != 1:
        return f"{path}: cells_hit must hold exactly one cell, got {hits!r}"
    if hits[0] not in required:
        return f"{path}: hit cell {hits[0]!r} is not one of its required cells"
    return _leaf_result_error(path, report["seed"])


def merge(run_dir: str | os.PathLike[str], feature_key: str) -> dict:
    """Union every artifact of ``feature_key`` under ``run_dir`` into one closure report."""
    root = Path(run_dir)
    errors: list[str] = []
    artifacts: list[dict] = []
    required_sets: dict[tuple[str, ...], list[str]] = {}
    hits: Counter[str] = Counter()
    for path in sorted(root.rglob(REPORT_NAME)):
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: unreadable artifact: {exc}")
            continue
        if not isinstance(report, dict) or report.get("feature_key") != feature_key:
            continue
        problem = _check_artifact(path, report)
        if problem:
            errors.append(problem)
            continue
        required_sets.setdefault(tuple(sorted(report["required_cells"])), []).append(str(path))
        hits[report["cells_hit"][0]] += 1
        artifacts.append(
            {"path": str(path), "seed": report["seed"], "cell": report["cells_hit"][0]}
        )
    if not artifacts and not errors:
        errors.append(f"no {REPORT_NAME} for {feature_key} under {root}")
    if len(required_sets) > 1:
        errors.append(
            "artifacts disagree on required_cells: "
            + "; ".join(f"{list(k)} in {v}" for k, v in sorted(required_sets.items()))
        )
    required = sorted({c for k in required_sets for c in k})
    missing = [c for c in required if c not in hits]
    return {
        "feature_key": feature_key,
        "run_dir": str(root),
        "artifacts": artifacts,
        "required_cells": required,
        "cells_hit": sorted(hits),
        "hit_counts": dict(sorted(hits.items())),
        "missing_cells": missing,
        "errors": errors,
        "satisfied": bool(required) and not missing and not errors,
    }


def _print_merge(merged: dict) -> None:
    print(f"feature  : {merged['feature_key']}")
    print(f"run dir  : {merged['run_dir']}")
    print(f"artifacts: {len(merged['artifacts'])}")
    print(f"required : {', '.join(merged['required_cells']) or '-'}")
    hit = ", ".join(f"{c} (x{n})" for c, n in merged["hit_counts"].items())
    print(f"hit      : {hit or '-'}")
    print(f"missing  : {', '.join(merged['missing_cells']) or '-'}")
    for error in merged["errors"]:
        print(f"error    : {error}")
    print(f"satisfied: {str(merged['satisfied']).lower()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("merge", help="union the cells under a run directory and grade closure")
    cmd.add_argument("run_dir", type=Path, help="run directory searched recursively")
    cmd.add_argument("--feature", required=True, help="feature_key to merge")
    cmd.add_argument(
        "--out",
        type=Path,
        help="merged report path (default: <run_dir>/functional-coverage-merge-<feature>.json)",
    )
    args = parser.parse_args(argv)

    if not args.run_dir.is_dir():
        parser.error(f"{args.run_dir} is not a directory")
    merged = merge(args.run_dir, args.feature)
    out = args.out or args.run_dir / f"functional-coverage-merge-{args.feature}.json"
    out.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    _print_merge(merged)
    print(f"merged   : {out}")
    return 0 if merged["satisfied"] else 1


if __name__ == "__main__":
    sys.exit(main())
