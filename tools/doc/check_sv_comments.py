#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Check the RTL comment shape on hand-maintained SystemVerilog modules.

Fails when the two-part // header after the SPDX lines is missing, when a
parameter or port of any module in the file has no same-line // clause, when
a // line sits between two of those declarations, or when a banned banner or
tag is present. A clause may continue on the next // lines when each one starts at
or right of the clause's //. A clause that only restates the declared name,
repeats a literal default, is a single word, or repeats another clause of the
same module also fails.
"""

import argparse
import re
import sys
from pathlib import Path

from sv_comment_text import DECL_START, clause, declared_name, header_prose, rtl_blocks, rtl_sources

_BANNED = re.compile(
    r"@file\b|@brief\b|@param\b|@details\b|@author\b"
    r"|//\s*File:|//\s*Module:|//\s*Author:"
)
_DECL = re.compile(r"^\s*(parameter|localparam|input|output|inout)\b")
_COMMENT_ONLY = re.compile(r"^\s*//")
_GENERATED = "chipyard_generated_files"


def _header_spans(lines):
    """(start, end) of each module/package/interface header, through its closing ');'."""
    spans = []
    i = 0
    while i < len(lines):
        if not DECL_START.match(lines[i]):
            i += 1
            continue
        start = i
        if re.match(r"^\s*package\b", lines[start]):
            spans.append((start, start))
            i += 1
            continue
        depth = 0
        begun = False
        end = len(lines) - 1
        for j in range(start, len(lines)):
            depth += lines[j].count("(") - lines[j].count(")")
            if "(" in lines[j]:
                begun = True
            if begun and depth <= 0:
                end = j
                break
        spans.append((start, end))
        i = end + 1
    return spans


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _clause_errors(path, line_no, name, text, seen):
    """A clause that restates the name, repeats a literal default, is one word, or repeats another."""
    errors = []
    stem = re.sub(r"_(n?[io]|n?io)$", "", name)
    if (
        _norm(text) in {_norm(name), _norm(stem)}
        or re.fullmatch(r"[BHDbhd][0-9a-fA-FxXzZ_]+\.?", text)
        or len(text.rstrip(".").split()) < 2
    ):
        errors.append(f"{path}:{line_no}: clause does not describe {name}")
    key = " ".join(text.lower().split())
    if key in seen:
        errors.append(f"{path}:{line_no}: clause of {name} repeats the clause of {seen[key]}")
    else:
        seen[key] = name
    return errors


def check(path: Path) -> list:
    lines = path.read_text(errors="replace").splitlines()
    errors = [
        f"{path}:{i}: banned comment tag or banner"
        for i, line in enumerate(lines, 1)
        if _BANNED.search(line)
    ]
    spans = _header_spans(lines)
    if not spans:
        return errors
    if len([p for p in header_prose(lines).splitlines() if p]) < 2:
        errors.append(f"{path}:1: missing two-part // header after the SPDX lines")

    for start, end in spans:
        prev_decl = False
        seen = {}
        i = start
        while i <= end:
            line = lines[i]
            if _DECL.match(line):
                prev_decl = True
                if "//" not in line:
                    errors.append(f"{path}:{i + 1}: declaration has no same-line // clause")
                    i += 1
                    continue
                text, nxt = clause(lines, i)
                name = declared_name(line.split("//", 1)[0])
                errors.extend(_clause_errors(path, i + 1, name, text, seen))
                i = nxt
                continue
            if _COMMENT_ONLY.match(line):
                if prev_decl and line.strip() != "//":
                    errors.append(f"{path}:{i + 1}: // line between declarations")
            elif line.strip():
                prev_decl = False
            i += 1
    return errors


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="*", type=Path)
    p.add_argument(
        "--root",
        type=Path,
        help="also check every source the RTL Modules Reference documents, except generated CPU RTL",
    )
    args = p.parse_args()
    paths = list(args.paths)
    if args.root:
        for _group, _slug, rtl in rtl_blocks(args.root):
            paths += [f for f in rtl_sources(rtl) if _GENERATED not in f.parts]
    if not paths:
        p.error("no paths given")
    errors = []
    for path in paths:
        errors.extend(check(path))
    for err in errors:
        print(err, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
