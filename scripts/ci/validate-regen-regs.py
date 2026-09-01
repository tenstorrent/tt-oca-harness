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
    result = subprocess.run(
        [
            "git",
            "-C",
            str(tree),
            "ls-files",
            "-z",
            "--",
            ":(glob)**/gen/py/*.py",
        ],
        check=True,
        capture_output=True,
    )
    return [tree / Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]


def generated_json(tree: Path) -> list[Path]:
    return sorted(tree.glob("**/regs/gen/json/*.json"))


def main() -> int:
    trees = [Path(arg).resolve() for arg in (sys.argv[1:] or ["."])]
    nested_roots = {
        tree: [other for other in trees if other != tree and other.is_relative_to(tree)]
        for tree in trees
    }

    python_count = 0
    json_count = 0
    for tree in trees:
        for path in tracked_generated_python(tree):
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            python_count += 1

        for path in generated_json(tree):
            if any(path.is_relative_to(nested) for nested in nested_roots[tree]):
                continue
            with path.open(encoding="utf-8") as stream:
                json.load(stream)
            json_count += 1

    print(
        f"Validated {python_count} generated Python header(s) and "
        f"{json_count} generated JSON model(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
