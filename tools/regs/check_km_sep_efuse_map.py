#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Fail if KM and SEP generated eFuse-map [11:0] offsets disagree.

KM includes ``sep_efuse_map.rdl`` and emits its own address header. Hardware
remaps KM-local ``0x0001_1xxx`` to SEP ``0x1093_0xxx`` by replacing ``[31:12]``,
so field offsets in ``[11:0]`` must match. ``regen-regs-diff`` only notices when
KM's own RDL or include timestamps make KM gen stale; it does not compare the
two maps. This check is that comparison.

A mismatch means regenerate KM from the RDL (``make regen-regs TARGET=key_manager``),
not a firmware literal in one image.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

OFFSET_MASK = 0xFFF

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_KM = _REPO / "hw/ip/key_manager/regs/gen/c/key_manager_addr.h"
DEFAULT_SEP = _REPO / "hw/sys/sep/regs/gen/c/sep_addr.h"

# Window BASE_ADDR (no field name) is skipped: ``+`` requires a field stem.
_FIELD_RE = re.compile(
    r"^#define\s+"
    r"(?:KEY_MANAGER_OTP_EFUSE_MAP_|OCH_SEP_TOP_SEP_EFUSE_MAP_)"
    r"([A-Z0-9_]+)_BASE_ADDR\s+(0x[0-9A-Fa-f]+)\s*$"
)


def parse_map_fields(text: str) -> dict[str, int]:
    fields: dict[str, int] = {}
    for line in text.splitlines():
        match = _FIELD_RE.match(line)
        if match is None:
            continue
        fields[match.group(1)] = int(match.group(2), 16)
    return fields


def offset_mismatches(km: dict[str, int], sep: dict[str, int]) -> list[str]:
    lines: list[str] = []
    for name in sorted(sep.keys() - km.keys()):
        lines.append(f"  {name}: present in SEP, missing from KM")
    for name in sorted(km.keys() - sep.keys()):
        lines.append(f"  {name}: present in KM, missing from SEP")
    for name in sorted(km.keys() & sep.keys()):
        km_off = km[name] & OFFSET_MASK
        sep_off = sep[name] & OFFSET_MASK
        if km_off != sep_off:
            lines.append(
                f"  {name}: KM [11:0]=0x{km_off:03X} (0x{km[name]:08X}) "
                f"SEP [11:0]=0x{sep_off:03X} (0x{sep[name]:08X})"
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--km", type=Path, default=DEFAULT_KM, help="key_manager_addr.h")
    parser.add_argument("--sep", type=Path, default=DEFAULT_SEP, help="sep_addr.h")
    args = parser.parse_args(argv)

    for path, label in ((args.km, "KM"), (args.sep, "SEP")):
        if not path.is_file():
            print(f"error: {label} address header not found: {path}", file=sys.stderr)
            return 1

    km = parse_map_fields(args.km.read_text())
    sep = parse_map_fields(args.sep.read_text())
    if not sep:
        print(f"error: no SEP eFuse-map BASE_ADDR symbols in {args.sep}", file=sys.stderr)
        return 1

    mismatches = offset_mismatches(km, sep)
    if mismatches:
        print(
            "error: KM and SEP eFuse-map [11:0] offsets disagree. "
            "Regenerate KM from the RDL (`make regen-regs TARGET=key_manager`); "
            "do not hardcode an offset in firmware.",
            file=sys.stderr,
        )
        print("\n".join(mismatches), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
