#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Union DTP debug-disable FCOV artifacts and enforce the 22-cell contract.

Usage:
    dbg_disable_cov_report.py <run-dir-or-artifact> [more paths...]

Each argument is a ``dbg_disable_fcov_*.json`` artifact or a directory to
search recursively. The report unions every artifact's hit cells and exits
non-zero unless all 22 required (field, disable_value, outcome) cells are
covered.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# Load the canonical field list directly from its file: the env package
# __init__ pulls in simulator-only dependencies this tool must not need.
_META = Path(__file__).resolve().parents[1] / "cocotb" / "env" / "dtp_dbg_disable.py"
_spec = importlib.util.spec_from_file_location("dtp_dbg_disable", _META)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DBG_DISABLE_FIELDS = _mod.DBG_DISABLE_FIELDS

REQUIRED = tuple(
    f"{field}:{value}:{outcome}"
    for field in DBG_DISABLE_FIELDS
    for value, outcome in ((0, "allowed"), (1, "blocked"))
)


def collect(paths: list[str]) -> list[Path]:
    artifacts: list[Path] = []
    for arg in paths:
        p = Path(arg)
        if p.is_dir():
            artifacts.extend(sorted(p.rglob("dbg_disable_fcov_*.json")))
        elif p.is_file():
            artifacts.append(p)
        else:
            print(f"error: {arg} does not exist", file=sys.stderr)
            sys.exit(2)
    return artifacts


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    artifacts = collect(argv)
    if not artifacts:
        print("error: no dbg_disable_fcov_*.json artifacts found", file=sys.stderr)
        return 2

    hit: set[str] = set()
    mask_classes: dict[str, int] = {}
    aux: dict[str, int] = {}
    for path in artifacts:
        payload = json.loads(path.read_text())
        if payload.get("artifact_type") != "dbg_disable_fcov":
            continue
        hit.update(payload.get("cells_hit", []))
        for name, count in payload.get("mask_classes", {}).items():
            mask_classes[name] = mask_classes.get(name, 0) + count
        for name, count in payload.get("aux_bins", {}).items():
            aux[name] = aux.get(name, 0) + count
        print(f"artifact: {path} ({payload.get('feature_key')}, "
              f"{len(payload.get('cells_hit', []))} cells, seed={payload.get('seed')})")

    print()
    print(f"{'cell':45s} status")
    missing = []
    for cell in REQUIRED:
        covered = cell in hit
        if not covered:
            missing.append(cell)
        print(f"{cell:45s} {'COVERED' if covered else 'MISSING'}")
    print()
    print(f"mask classes: {mask_classes}")
    print(f"aux bins:     {aux}")
    print()
    print(f"required cells covered: {len(REQUIRED) - len(missing)}/{len(REQUIRED)}")
    if missing:
        print(f"FAIL: missing cells: {missing}")
        return 1
    print("PASS: all required debug-disable cells covered")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
