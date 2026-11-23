#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Four-cell {PRIMARY_CHIPLET, BOOT_RECOVERY} closure for smc_occp_boot_sequence_status_test.

Each passing leaf writes one cell to ARTIFACT_NAME in its run directory. ``merge`` reads a
run_dv run directory, keeps the cells of runs whose leaf result is PASS, and reports the union
against REQUIRED_CELLS. The dual target collects no simulator coverage, so this union is the
closure record.

    smc_rom_mode_coverage.py merge <run-dir> [--out FILE]

exits 0 only when every required cell is hit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARTIFACT_NAME = "smc_rom_mode_coverage.json"
ARTIFACT_TYPE = "functional-coverage-report"
FEATURE_KEY = "SMC-ROM-BOOT-MODE-STATUS"


def cell_name(primary: bool, recovery: bool) -> str:
    return f"primary={int(primary)},recovery={int(recovery)}"


REQUIRED_CELLS = tuple(cell_name(p, r) for p in (False, True) for r in (False, True))


def leaf_artifact(*, seed: int, primary: bool, recovery: bool) -> dict:
    cells = [cell_name(primary, recovery)]
    return {
        "artifact_type": ARTIFACT_TYPE,
        "feature_key": FEATURE_KEY,
        "seed": seed,
        "required_cells": list(REQUIRED_CELLS),
        "cells_hit": cells,
        "measurements": {"primary": int(primary), "recovery": int(recovery)},
        "satisfied": set(REQUIRED_CELLS) <= set(cells),
    }


def write_leaf_artifact(path: Path, *, seed: int, primary: bool, recovery: bool) -> Path:
    path.write_text(
        json.dumps(leaf_artifact(seed=seed, primary=primary, recovery=recovery), indent=2) + "\n"
    )
    return path


def load_leaf_artifact(path: Path) -> dict:
    data = json.loads(path.read_text())
    problems = []
    if data.get("artifact_type") != ARTIFACT_TYPE:
        problems.append(f"artifact_type {data.get('artifact_type')!r}")
    if data.get("feature_key") != FEATURE_KEY:
        problems.append(f"feature_key {data.get('feature_key')!r}")
    if list(data.get("required_cells", [])) != list(REQUIRED_CELLS):
        problems.append(f"required_cells {data.get('required_cells')!r}")
    cells = data.get("cells_hit")
    if not isinstance(cells, list) or len(cells) != 1 or cells[0] not in REQUIRED_CELLS:
        problems.append(f"cells_hit {cells!r}")
    else:
        meas = data.get("measurements", {})
        if cell_name(bool(meas.get("primary")), bool(meas.get("recovery"))) != cells[0]:
            problems.append(f"measurements {meas!r} disagree with {cells[0]}")
    if not isinstance(data.get("seed"), int):
        problems.append(f"seed {data.get('seed')!r}")
    if problems:
        raise ValueError(f"{path}: not a {FEATURE_KEY} leaf artifact: {'; '.join(problems)}")
    return data


def _attempt_dir(run_dir: Path, results_xml: str) -> Path:
    # result.json paths are repository-relative; rebase them on the run directory given.
    parts = Path(results_xml).parts
    if run_dir.name not in parts:
        raise ValueError(f"{results_xml} is not under {run_dir}")
    rel = parts[parts.index(run_dir.name) + 1 :]
    return run_dir.joinpath(*rel).parent.parent


def merge(run_dir: Path) -> dict:
    """Union of the cells of every PASS run in ``run_dir`` that wrote a leaf artifact."""
    hits: dict[str, list[int]] = {cell: [] for cell in REQUIRED_CELLS}
    passing: list[dict] = []
    excluded: list[dict] = []
    for leaf in sorted(run_dir.glob("*/result.json")):
        result = json.loads(leaf.read_text())
        for run in result.get("runs", []):
            xml = run.get("artifacts", {}).get("results_xml")
            if xml is None:
                continue
            artifacts = sorted(_attempt_dir(run_dir, xml).rglob(ARTIFACT_NAME))
            if not artifacts:
                continue
            entry = {"leaf": result.get("item"), "seed": run.get("seed"), "status": run["status"]}
            if run.get("status") != "PASS":
                excluded.append(entry)
                continue
            if len(artifacts) != 1:
                raise ValueError(f"{leaf.parent}: {len(artifacts)} {ARTIFACT_NAME} for one run")
            data = load_leaf_artifact(artifacts[0])
            if data["seed"] != run.get("seed"):
                raise ValueError(
                    f"{artifacts[0]} records seed {data['seed']}, the run was seed {run['seed']}"
                )
            hits[data["cells_hit"][0]].append(data["seed"])
            passing.append({**entry, "cell": data["cells_hit"][0]})
    missing = [cell for cell, seeds in hits.items() if not seeds]
    return {
        "artifact_type": ARTIFACT_TYPE,
        "feature_key": FEATURE_KEY,
        "run_dir": str(run_dir),
        "required_cells": list(REQUIRED_CELLS),
        "cells_hit": [cell for cell, seeds in hits.items() if seeds],
        "measurements": {"seeds_per_cell": hits, "passing_runs": passing, "excluded": excluded},
        "missing_cells": missing,
        "satisfied": not missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    merge_cmd = sub.add_parser("merge", help="union the passing leaf artifacts of a run")
    merge_cmd.add_argument("run_dir", type=Path)
    merge_cmd.add_argument("--out", type=Path, help="also write the merged report here")
    args = parser.parse_args(argv)

    report = merge(args.run_dir.resolve())
    text = json.dumps(report, indent=2) + "\n"
    if args.out is not None:
        args.out.write_text(text)
    sys.stdout.write(text)
    if not report["satisfied"]:
        sys.stderr.write(f"missing cells: {', '.join(report['missing_cells'])}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
