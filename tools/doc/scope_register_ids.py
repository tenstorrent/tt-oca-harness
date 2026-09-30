#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Scope generated HTML fragments so multiple register maps can share a page."""

import re
import sys
from pathlib import Path


def scope_ids(text: str, namespace: str) -> str:
    ids = set(re.findall(r'\bid="([^"]+)"', text))
    text = re.sub(
        r'\bid="([^"]+)"',
        lambda m: m[0] if m[1].startswith('regmap-') else f'id="{namespace}-{m[1]}" data-register-alias="{m[1]}"',
        text,
    )
    return re.sub(
        r'\bhref="#([^"]+)"',
        lambda m: f'href="#{namespace}-{m[1]}"' if m[1] in ids and not m[1].startswith('regmap-') else m[0],
        text,
    )


def main() -> None:
    source, destination = map(Path, sys.argv[1:])
    for path in source.rglob("*.html"):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(scope_ids(path.read_text(), path.stem))


if __name__ == "__main__":
    main()
