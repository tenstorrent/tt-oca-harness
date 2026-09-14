#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unwrap `@login` code spans in gh-aw comment JSON so GitHub notifies."""

import os
import re
import sys
from pathlib import Path

# Teams (@org/team) stay wrapped. Logins: 1–39 [A-Za-z0-9-], no edge hyphen.
SPAN = re.compile(r"`(@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)`")
PATHS = (
    "/tmp/gh-aw/agent_output.json",
    "/tmp/gh-aw/safeoutputs.jsonl",
    os.environ.get("GH_AW_SAFE_OUTPUTS", ""),
)


def rewrite(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        return
    text = path.read_text(encoding="utf-8")
    new = SPAN.sub(r"\1", text)
    if new != text:
        path.write_text(new, encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        assert SPAN.sub(r"\1", "`@minshaohoTT` x") == "@minshaohoTT x"
        assert SPAN.sub(r"\1", "`@org/team`") == "`@org/team`"
        raise SystemExit(0)
    seen: set[Path] = set()
    for raw in (*sys.argv[1:], *PATHS):
        path = Path(raw)
        if raw and path not in seen:
            seen.add(path)
            rewrite(path)
