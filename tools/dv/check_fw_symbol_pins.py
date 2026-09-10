#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# check_fw_symbol_pins.py
#
# Verifies that a hand-committed header pinning firmware PCs still matches the
# symbol table of the image those PCs came from.
#
# sep_debug_bus_symbols.h pins the PCs the CLA matches on. Its own #error
# guards only catch a zero value and a trace16 collision, so an image rebuilt
# with the PCs at other plausible addresses passes every guard while the CLA
# matches the wrong instruction -- the test still goes green, on the wrong
# evidence. The .sym the firmware build already emits is the authority; this
# compares the two.
#
# Usage:
#   python3 tools/dv/check_fw_symbol_pins.py            # check every pin
#   python3 tools/dv/check_fw_symbol_pins.py --update   # rewrite to match .sym
#
# Exit codes:
#   0   Every pin matches the built symbol table.
#   1   A pin disagrees, a required .sym is absent, or a cookie is unpinned.
#   2   Configuration or argument error.

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Pin(NamedTuple):
    header: str  # repo-relative header carrying the #define
    macro: str  # macro name holding the full PC
    sym: str  # repo-relative .sym emitted by the firmware build
    symbol: str  # symbol name whose address the macro must equal


# Extend as more images pin PCs. Keeping this in the script rather than a
# sidecar keeps the pin and its authority in one reviewable place.
PINS = [
    Pin(
        "hw/sys/sep/dv/fw/tests/common/sep_debug_bus_symbols.h",
        "DEBUG_BUS_WAIT_PC",
        "hw/sys/sep/dv/fw/build/tests/sep_smu_debug_bus/sep_smu_debug_bus.tcm.sym",
        "debug_bus_wait_for_go",
    ),
    Pin(
        "hw/sys/sep/dv/fw/tests/common/sep_debug_bus_symbols.h",
        "DEBUG_BUS_MARKER_PC",
        "hw/sys/sep/dv/fw/build/tests/sep_smu_debug_bus/sep_smu_debug_bus.tcm.sym",
        "debug_bus_marker",
    ),
]

# `nm -B -n` output: "c00001de T debug_bus_wait_for_go"
_SYM_RE = re.compile(r"^([0-9a-fA-F]+)\s+\S\s+(\S+)\s*$")


def _symbol_addresses(sym_path: Path) -> dict[str, int]:
    table: dict[str, int] = {}
    for line in sym_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SYM_RE.match(line)
        if m:
            table[m.group(2)] = int(m.group(1), 16)
    return table


def _macro_value(text: str, macro: str) -> int | None:
    m = re.search(rf"^#define\s+{re.escape(macro)}\s+0x([0-9a-fA-F]+)u?\s*$", text, re.M)
    return int(m.group(1), 16) if m else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check firmware PC pins against the built symbol table."
    )
    parser.add_argument("--update", action="store_true", help="rewrite the pins to match the .sym")
    args = parser.parse_args(argv)

    checked = 0
    failures: list[str] = []
    edits: dict[Path, str] = {}

    for pin in PINS:
        sym_path = _REPO_ROOT / pin.sym
        header_path = _REPO_ROOT / pin.header
        if not header_path.is_file():
            print(f"error: {pin.header} does not exist", file=sys.stderr)
            return 2
        if not sym_path.is_file():
            failures.append(
                f"{pin.sym}:1:1: error: symbol table is absent; {pin.header} "
                f"still pins {pin.macro}. Build the image, then rerun."
            )
            continue

        table = _symbol_addresses(sym_path)
        if pin.symbol not in table:
            failures.append(
                f"{pin.sym}:1:1: error: symbol {pin.symbol} is absent from the built image, "
                f"but {pin.header} still pins {pin.macro} to it"
            )
            continue

        text = edits.get(header_path) or header_path.read_text(encoding="utf-8")
        pinned = _macro_value(text, pin.macro)
        if pinned is None:
            print(f"error: {pin.header} has no #define {pin.macro}", file=sys.stderr)
            return 2

        actual = table[pin.symbol]
        checked += 1
        if pinned == actual:
            continue

        if args.update:
            edits[header_path] = re.sub(
                rf"^(#define\s+{re.escape(pin.macro)}\s+)0x[0-9a-fA-F]+u?\s*$",
                rf"\g<1>0x{actual:08x}u",
                text,
                flags=re.M,
            )
        else:
            line_no = next(
                (
                    i
                    for i, ln in enumerate(text.splitlines(), start=1)
                    if ln.startswith(f"#define {pin.macro} ")
                ),
                1,
            )
            failures.append(
                f"{pin.header}:{line_no}:1: error: {pin.macro} is 0x{pinned:08x} but "
                f"{pin.symbol} is at 0x{actual:08x} in {Path(pin.sym).name}. The CLA would "
                f"match the wrong instruction. Rerun with --update after rebuilding."
            )

    if args.update and edits:
        for path, text in edits.items():
            path.write_text(text, encoding="utf-8")
            print(f"updated {path.relative_to(_REPO_ROOT)}")
        return 0

    for line in failures:
        print(line)
    if failures:
        print(f"\ncheck_fw_symbol_pins: {len(failures)} pin error(s)", file=sys.stderr)
        return 1

    print(f"check_fw_symbol_pins: OK -- {checked} pin(s) verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
