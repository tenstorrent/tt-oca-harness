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

_BANNED = re.compile(
    r"@file\b|@brief\b|@param\b|@details\b|@author\b"
    r"|//\s*File:|//\s*Module:|//\s*Author:"
)
_DECL = re.compile(r"^\s*(parameter|localparam|input|output|inout)\b")
_COMMENT_ONLY = re.compile(r"^\s*//")
_ASSIGN = re.compile(r"(?<![=!<>])=(?!=)")
_SPDX = re.compile(r"^\s*//\s*(SPDX-|Copyright)")


def _header_spans(lines):
    """(start, end) of each module/package/interface header, through its closing ');'."""
    spans = []
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*(module|interface|package)\b", lines[i]):
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


def check(path: Path) -> list:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    errors = []
    for i, line in enumerate(lines, 1):
        if _BANNED.search(line):
            errors.append(f"{path}:{i}: banned comment tag or banner")

    spans = _header_spans(lines)
    if not spans:
        return errors
    mod_start = spans[0][0]

    prose = []
    for line in lines[:mod_start]:
        if _SPDX.match(line) or not line.strip():
            continue
        if line.strip().startswith("//"):
            prose.append(line.strip()[2:].strip())
        else:
            break
    if len([p for p in prose if p]) < 2:
        errors.append(f"{path}: missing two-part // header after the SPDX lines")

    for start, end in spans:
        prev_decl = False
        clause_col = None
        for i in range(start, end + 1):
            line = lines[i]
            if _DECL.match(line):
                if "//" not in line:
                    errors.append(f"{path}:{i + 1}: declaration has no same-line // clause")
                    clause_col = None
                else:
                    clause_col = line.index("//")
                prev_decl = True
                continue
            if _COMMENT_ONLY.match(line):
                if clause_col is not None and line.index("//") >= clause_col:
                    continue
                clause_col = None
                if prev_decl and line.strip() != "//":
                    errors.append(f"{path}:{i + 1}: // line between declarations")
                continue
            clause_col = None
            if line.strip():
                prev_decl = False
        errors.extend(_empty_clauses(path, lines, start, end))
    return errors


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _empty_clauses(path, lines, start, end):
    """Clauses that restate the name, repeat a literal default, are one word, or repeat another clause."""
    errors = []
    seen = {}
    i = start
    while i <= end:
        line = lines[i]
        if not (_DECL.match(line) and "//" in line):
            i += 1
            continue
        code, text = line.split("//", 1)
        col = line.index("//")
        j = i + 1
        while j <= end and _COMMENT_ONLY.match(lines[j]) and lines[j].index("//") >= col:
            text += " " + lines[j].split("//", 1)[1]
            j += 1
        head = re.sub(r"\[[^\]]*\]", " ", _ASSIGN.split(code, 1)[0])
        idents = re.findall(r"[A-Za-z_][\w$]*", head)
        name = idents[-1] if idents else ""
        text = text.strip()
        stem = re.sub(r"_(n?[io]|n?io)$", "", name)
        if (
            _norm(text) in {_norm(name), _norm(stem)}
            or re.fullmatch(r"[BHDbhd][0-9a-fA-FxXzZ_]+\.?", text)
            or len(text.rstrip(".").split()) < 2
        ):
            errors.append(f"{path}:{i + 1}: clause does not describe {name}")
        key = " ".join(text.lower().split())
        if key in seen:
            errors.append(f"{path}:{i + 1}: clause of {name} repeats the clause of {seen[key]}")
        else:
            seen[key] = name
        i = j
    return errors


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="+", type=Path)
    args = p.parse_args()
    errors = []
    for path in args.paths:
        errors.extend(check(path))
    for err in errors:
        print(err, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
