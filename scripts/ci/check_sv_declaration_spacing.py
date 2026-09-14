#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reject unstable whitespace in hand-maintained SystemVerilog declarations."""

import re
import sys
from pathlib import Path

PADDED_DECLARATION = re.compile(
    r"(?:^|[(;,])\s*(?:"
    r"input|output|inout|ref|parameter|localparam|typedef|const|var|"
    r"wire|wand|wor|tri|reg|logic|bit|byte|shortint|int|longint|integer|time|"
    r"[A-Za-z_][A-Za-z0-9_$:]*_t"
    r")\b.*\[\s+\S"
)
STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def main(paths: list[str]) -> int:
    diagnostics: list[str] = []
    for name in paths:
        path = Path(name)
        lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
        for line_number, line in enumerate(lines, start=1):
            location = f"{path}:{line_number}"
            if "\t" in line:
                diagnostics.append(f"{location}: tab character")
            code = STRING.sub('""', line).split("//", maxsplit=1)[0]
            if PADDED_DECLARATION.search(code):
                diagnostics.append(f"{location}: padding immediately after '[' in declaration")
    if diagnostics:
        print("\n".join(diagnostics), file=sys.stderr)
    return int(bool(diagnostics))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
