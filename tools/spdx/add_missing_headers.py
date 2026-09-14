#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Add Apache-2.0 + Tenstorrent SPDX headers to files the scanner classifies as missing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_license_headers import REPO, classify, tracked_files, wanted  # noqa: E402

SPDX_ID = "SPDX-License-Identifier: Apache-2.0"
SPDX_COPY = "SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc."

STYLE = {
    ".sv": "//",
    ".svh": "//",
    ".v": "//",
    ".vh": "//",
    ".rdl": "//",
    ".vlt": "//",
    ".py": "#",
    ".mk": "#",
    ".tcl": "#",
    ".sh": "#",
    ".yml": "#",
    ".yaml": "#",
    ".hjson": "#",
    ".toml": "#",
    ".cfg": "#",
    ".f": "#",
    ".core": "#",
    ".c": "c",
    ".h": "c",
    ".cc": "c",
    ".cpp": "c",
    ".ld": "c",
    ".S": "c",
}


def header_for(path: Path) -> str | None:
    if path.name in {"Makefile", "makefile", "Dockerfile"}:
        style = "#"
    else:
        style = STYLE.get(path.suffix)
    if style is None:
        return None
    if style == "c":
        return f"/* {SPDX_ID} */\n/* {SPDX_COPY} */\n\n"
    return f"{style} {SPDX_ID}\n{style} {SPDX_COPY}\n\n"


def add_header(rel: str) -> bool:
    path = REPO / rel
    hdr = header_for(path)
    if hdr is None:
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("#!"):
        first, rest = text.split("\n", 1)
        text = first + "\n" + hdr + rest
    else:
        text = hdr + text
    path.write_text(text, encoding="utf-8")
    return True


def match_scope(path: str, scope: str) -> bool:
    if scope == "hw-rtl":
        return path.startswith("hw/") and not any(
            p in f"/{path}/" for p in ("/dv/", "/fw/", "/bootrom/")
        )
    if scope == "dv-fw":
        return any(p in f"/{path}/" for p in ("/dv/", "/fw/", "/bootrom/"))
    if scope == "tools":
        return path.startswith(("tools/", "scripts/", "flows/", "doc/", ".github/"))
    return True


def main() -> int:
    scope = sys.argv[1] if len(sys.argv) > 1 else "all"
    n = 0
    for path in tracked_files():
        if not wanted(path) or not match_scope(path, scope):
            continue
        cls, _ = classify(path)
        if cls != "missing":
            continue
        if add_header(path):
            n += 1
            print(path)
    print(f"added headers to {n} missing file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
