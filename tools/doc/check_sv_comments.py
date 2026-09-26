#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Check the RTL comment shape on hand-maintained SystemVerilog modules.

Fails when the two-part // header after the SPDX lines is missing, when a
parameter or port in the header has no same-line // clause, when a // line
sits between two of those declarations, or when a banned banner or tag is
present.
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
_SPDX = re.compile(r"^\s*//\s*(SPDX-|Copyright)")


def _header_span(lines):
    """Lines of the module/package/interface header, through its closing ');'."""
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*(module|interface|package)\b", line):
            start = i
            break
    if start is None:
        return None, None
    if re.match(r"^\s*package\b", lines[start]):
        return start, start
    depth = 0
    begun = False
    for i in range(start, len(lines)):
        depth += lines[i].count("(") - lines[i].count(")")
        if "(" in lines[i]:
            begun = True
        if begun and depth <= 0:
            return start, i
    return start, len(lines) - 1


def check(path: Path) -> list:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    errors = []
    for i, line in enumerate(lines, 1):
        if _BANNED.search(line):
            errors.append(f"{path}:{i}: banned comment tag or banner")

    mod_start, mod_end = _header_span(lines)
    if mod_start is None:
        return errors

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

    prev_decl = False
    for i in range(mod_start, mod_end + 1):
        line = lines[i]
        if _DECL.match(line):
            if "//" not in line:
                errors.append(f"{path}:{i + 1}: declaration has no same-line // clause")
            prev_decl = True
            continue
        if prev_decl and _COMMENT_ONLY.match(line) and line.strip() != "//":
            errors.append(f"{path}:{i + 1}: // line between declarations")
        if line.strip() and not _COMMENT_ONLY.match(line):
            prev_decl = False
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
