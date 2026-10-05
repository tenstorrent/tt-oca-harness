#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Prepend a Tenstorrent Apache-2.0 SPDX header when one is missing.

Used by the register generators so PeakRDL and custom exporters leave
generated files with a license header. Also safe to run on a directory of
already-committed collateral.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SPDX_ID = "SPDX-License-Identifier: Apache-2.0"
SPDX_COPY = "SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc."

HEADERS = {
    ".sv": f"// {SPDX_ID}\n// {SPDX_COPY}\n\n",
    ".svh": f"// {SPDX_ID}\n// {SPDX_COPY}\n\n",
    ".v": f"// {SPDX_ID}\n// {SPDX_COPY}\n\n",
    ".vh": f"// {SPDX_ID}\n// {SPDX_COPY}\n\n",
    ".c": f"/* {SPDX_ID} */\n/* {SPDX_COPY} */\n\n",
    ".h": f"/* {SPDX_ID} */\n/* {SPDX_COPY} */\n\n",
    ".py": f"# {SPDX_ID}\n# {SPDX_COPY}\n\n",
    ".rdl": f"// {SPDX_ID}\n// {SPDX_COPY}\n\n",
    ".adoc": f"// {SPDX_ID}\n// {SPDX_COPY}\n\n",
    ".html": f"<!-- {SPDX_ID} -->\n<!-- {SPDX_COPY} -->\n",
    ".xml": f"<!-- {SPDX_ID} -->\n<!-- {SPDX_COPY} -->\n",
}

# An XML declaration, when present, must stay the very first thing in the file,
# so the SPDX comment is inserted immediately after it rather than prepended.
_XML_DECL_RE = re.compile(r"^<\?xml[^>]*\?>\s*\n")


def stamp_file(path: Path) -> bool:
    if path.suffix not in HEADERS:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    original = text
    if path.suffix == ".xml":
        ending = "\n" if text.endswith("\n") else ""
        text = "\n".join(line.rstrip() for line in text.splitlines()) + ending
    if "SPDX-License-Identifier" not in "\n".join(text.splitlines()[:25]):
        header = HEADERS[path.suffix]
        decl = _XML_DECL_RE.match(text) if path.suffix == ".xml" else None
        if decl:
            text = text[: decl.end()] + header + text[decl.end() :]
        else:
            text = header + text
    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def walk(root: Path) -> int:
    n = 0
    if root.is_file():
        return int(stamp_file(root))
    for path in root.rglob("*"):
        if path.is_file() and stamp_file(path):
            n += 1
    return n


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: stamp_spdx.py <file-or-dir> [...]", file=sys.stderr)
        return 2
    total = 0
    for arg in sys.argv[1:]:
        total += walk(Path(arg))
    print(f"stamped {total} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
