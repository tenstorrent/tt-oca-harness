#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reject a source path listed twice in one Bender.yml when both targets can match.

Bender keeps the first listing whose target matches, so such a file compiles at
a position that depends on the targets passed. Listings whose targets cannot
match together, such as the synthesis and emulation define groups, are allowed:
Bender drops the defines of a group that has no files.
"""

import re
import subprocess
from itertools import combinations, product

GROUP = re.compile(r"  - (?:target:\s*(.+?)\s*$)?")
SOURCE = re.compile(r"\s+- (\S+\.(?:sv|svh|v|vh))\s*$")
NAME = re.compile(r"\w+")
OPERATORS = {"__builtins__": {}, "any": lambda *a: True in a, "all": lambda *a: False not in a}


def listings(path: str) -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    in_sources, target = False, "all()"
    with open(path, encoding="utf-8") as manifest:
        for number, line in enumerate(manifest, start=1):
            if line[:1].strip() and not line.startswith("#"):
                in_sources = line.rstrip() == "sources:"
            if not in_sources:
                continue
            if group := GROUP.match(line):
                target = group[1] or "all()"
            if source := SOURCE.match(line):
                found.setdefault(source[1], []).append((number, target))
    return found


def match_together(left: str, right: str) -> bool:
    names = sorted(set(NAME.findall(f"{left} {right}")) - {"any", "all", "not"})
    for values in product((False, True), repeat=len(names)):
        scope = OPERATORS | dict(zip(names, values))
        if eval(left, scope) and eval(right, scope):
            return True
    return False


def main() -> int:
    manifests = subprocess.check_output(
        ["git", "ls-files", "Bender.yml", "**/Bender.yml"], text=True
    )
    problems = 0
    for path in manifests.split():
        for source, places in listings(path).items():
            for (line, left), (other, right) in combinations(places, 2):
                if match_together(left, right):
                    print(
                        f"{path}:{line}: {source} is also listed at line {other}; "
                        f"targets {left!r} and {right!r} can match together"
                    )
                    problems += 1
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
