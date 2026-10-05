#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# generate_fw_symbol_pins.py
#
# Writes the header the SMC DFD-arm image includes so the CLA can match the
# SEP retire-trace PCs. The .sym the firmware link already emits is the
# authority; the header is a build product, not a committed constant.
#
# Usage:
#   python3 tools/dv/generate_fw_symbol_pins.py \
#     --sym <image>.tcm.sym --output sep_debug_bus_symbols.h
#
# Exit codes:
#   0   Header written.
#   1   A required symbol is absent from the .sym.
#   2   Configuration or argument error.

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `nm -B -n` output: "c00001de T debug_bus_wait_for_go"
_SYM_RE = re.compile(r"^([0-9a-fA-F]+)\s+\S\s+(\S+)\s*$")

_HEADER = """\
/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * PCs the CLA matches on. Generated from the built SEP .sym when
 * sep_smu_debug_bus links. CLA snapshot[63:48] is (LOW16 << 2).
 */
#ifndef SEP_DEBUG_BUS_SYMBOLS_H
#define SEP_DEBUG_BUS_SYMBOLS_H

#define DEBUG_BUS_WAIT_PC 0x{wait_pc:08x}u
#define DEBUG_BUS_MARKER_PC 0x{marker_pc:08x}u
#define DEBUG_BUS_WAIT_LOW16 0x{wait_low16:04x}u
#define DEBUG_BUS_MARKER_LOW16 0x{marker_low16:04x}u
#define DEBUG_BUS_BOGUS_LOW16 0x{bogus_low16:04x}u
#define DEBUG_BUS_WAIT_TRACE16 ((DEBUG_BUS_WAIT_LOW16 << 2) & 0xFFFFu)
#define DEBUG_BUS_MARKER_TRACE16 ((DEBUG_BUS_MARKER_LOW16 << 2) & 0xFFFFu)
#define DEBUG_BUS_BOGUS_TRACE16 (DEBUG_BUS_MARKER_TRACE16 ^ 0x8000u)

#if DEBUG_BUS_MARKER_PC == 0 || DEBUG_BUS_WAIT_PC == 0
#error sep_debug_bus_symbols.h has a zero PC
#endif
#if DEBUG_BUS_WAIT_LOW16 != (DEBUG_BUS_WAIT_PC & 0xFFFFu)
#error DEBUG_BUS_WAIT_LOW16 does not match DEBUG_BUS_WAIT_PC
#endif
#if DEBUG_BUS_MARKER_LOW16 != (DEBUG_BUS_MARKER_PC & 0xFFFFu)
#error DEBUG_BUS_MARKER_LOW16 does not match DEBUG_BUS_MARKER_PC
#endif
#if DEBUG_BUS_MARKER_TRACE16 == DEBUG_BUS_WAIT_TRACE16
#error marker and wait trace16 collide
#endif
#if (DEBUG_BUS_BOGUS_TRACE16 == DEBUG_BUS_MARKER_TRACE16) || \\
    (DEBUG_BUS_BOGUS_TRACE16 == DEBUG_BUS_WAIT_TRACE16)
#error bogus match collides with marker or wait trace16
#endif

#endif /* SEP_DEBUG_BUS_SYMBOLS_H */
"""


def _symbol_addresses(sym_path: Path) -> dict[str, int]:
    table: dict[str, int] = {}
    for line in sym_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SYM_RE.match(line)
        if m:
            table[m.group(2)] = int(m.group(1), 16)
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate CLA PC pins from a firmware symbol table."
    )
    parser.add_argument("--sym", required=True, type=Path, help="nm -B -n symbol table")
    parser.add_argument("--output", required=True, type=Path, help="header to write")
    args = parser.parse_args(argv)

    if not args.sym.is_file():
        print(f"error: {args.sym} does not exist", file=sys.stderr)
        return 2

    table = _symbol_addresses(args.sym)
    missing = [name for name in ("debug_bus_wait_for_go", "debug_bus_marker") if name not in table]
    if missing:
        print(
            f"error: {args.sym}: missing symbol(s) {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    wait_pc = table["debug_bus_wait_for_go"]
    marker_pc = table["debug_bus_marker"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        _HEADER.format(
            wait_pc=wait_pc,
            marker_pc=marker_pc,
            wait_low16=wait_pc & 0xFFFF,
            marker_low16=marker_pc & 0xFFFF,
            bogus_low16=(marker_pc & 0xFFFF) ^ 0x8000,
        ),
        encoding="utf-8",
    )
    print(f"generated {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
