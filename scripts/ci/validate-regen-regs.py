#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Validate regenerated Python headers and transient JSON models."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def tracked_generated_python(tree: Path) -> list[Path]:
    args = ["git", "-C", str(tree), "ls-files", "-z", "--", ":(glob)**/gen/py/*.py"]
    result = subprocess.run(args, check=True, capture_output=True)
    return [tree / Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]


def generated_json(tree: Path) -> list[Path]:
    return sorted(tree.glob("**/regs/gen/json/*.json"))


def main() -> int:
    trees = [Path(arg).resolve() for arg in (sys.argv[1:] or ["."])]

    # A set (not a list) de-duplicates JSON files found twice because one
    # requested tree is nested inside another, e.g. "." also globs "nonfree".
    python_count = 0
    json_paths: set[Path] = set()
    for tree in trees:
        for path in tracked_generated_python(tree):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            python_count += 1
        json_paths.update(generated_json(tree))

    for path in json_paths:
        with path.open(encoding="utf-8") as stream:
            json.load(stream)

    print(
        f"Validated {python_count} generated Python header(s) and "
        f"{len(json_paths)} generated JSON model(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
