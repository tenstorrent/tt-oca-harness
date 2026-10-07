#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reject a source path listed twice in one Bender.yml when both targets can match.

Bender keeps the first listing whose target matches. Two listings that can be
true together therefore compile the file at different positions depending on
which targets were passed. Listings whose targets cannot be true together, such
as the synthesis and emulation define groups, stay: Bender drops the defines of
a group that has no files.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ATOM = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SOURCE = re.compile(r"\.(?:sv|svh|v|vh)\Z")
TARGET_LINE = re.compile(r"^  - target:\s*(.+?)\s*$")
FILE_LINE = re.compile(r"^ {4,}- (\S+)\s*$")


def split_args(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def parse(text: str):
    text = text.strip()
    for kind in ("any", "all", "not"):
        prefix = f"{kind}("
        if text.startswith(prefix) and text.endswith(")"):
            args = split_args(text[len(prefix) : -1])
            if kind == "not":
                if len(args) != 1:
                    raise ValueError(f"not() takes one argument: {text}")
                return ("not", parse(args[0]))
            if not args:
                raise ValueError(f"empty {kind}(): {text}")
            return (kind, [parse(arg) for arg in args])
    if not ATOM.fullmatch(text):
        raise ValueError(f"bad target expression: {text}")
    return ("atom", text)


def atoms(expr) -> set[str]:
    kind, value = expr
    if kind == "always":
        return set()
    if kind == "atom":
        return {value}
    if kind == "not":
        return atoms(value)
    return set().union(*(atoms(arg) for arg in value))


def evaluate(expr, chosen: set[str]) -> bool:
    kind, value = expr
    if kind == "always":
        return True
    if kind == "atom":
        return value in chosen
    if kind == "not":
        return not evaluate(value, chosen)
    if kind == "all":
        return all(evaluate(arg, chosen) for arg in value)
    return any(evaluate(arg, chosen) for arg in value)


def can_both_match(left, right) -> bool:
    names = sorted(atoms(left) | atoms(right))
    for mask in range(1 << len(names)):
        chosen = {name for bit, name in enumerate(names) if mask & (1 << bit)}
        if evaluate(left, chosen) and evaluate(right, chosen):
            return True
    return False


def listings(path: Path) -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    target = None
    in_files = False
    in_sources = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip() == "sources:":
            in_sources = True
            continue
        if not in_sources:
            continue
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        matched = TARGET_LINE.match(line)
        if matched:
            target = matched.group(1)
            in_files = False
            continue
        if line.strip() == "files:":
            in_files = True
            continue
        matched = FILE_LINE.match(line)
        if in_files and matched and SOURCE.search(matched.group(1)):
            found.setdefault(matched.group(1), []).append((number, target or "always"))
    return found


def manifests(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "**/Bender.yml", "Bender.yml"],
        cwd=root,
    )
    return [root / name.decode() for name in output.split(b"\0") if name]


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    problems = 0
    for path in manifests(root):
        try:
            grouped = listings(path)
        except (OSError, UnicodeError) as error:
            print(f"{path}: {error}", file=sys.stderr)
            problems += 1
            continue
        for source, places in grouped.items():
            if len(places) < 2:
                continue
            parsed = []
            for line, target in places:
                try:
                    parsed.append(
                        (line, target, ("always", None) if target == "always" else parse(target))
                    )
                except ValueError as error:
                    print(f"{path}:{line}: {error}", file=sys.stderr)
                    problems += 1
            for index, (line, target, expr) in enumerate(parsed):
                for other_line, other_target, other in parsed[index + 1 :]:
                    if can_both_match(expr, other):
                        print(
                            f"{path}:{line}: {source} is also listed at line "
                            f"{other_line}; targets {target!r} and {other_target!r} "
                            "can match together",
                            file=sys.stderr,
                        )
                        problems += 1
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
