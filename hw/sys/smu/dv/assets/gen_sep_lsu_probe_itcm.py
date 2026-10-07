#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Emit sep_lsu_probe.itcm.hex, the SEP ICCM image smu_sep_lsu_fabric_test runs.

The image is a few RV32I instructions the SEP debug module points the hart at;
the test sets the registers, resumes the hart and collects the result once
``ebreak`` returns it to debug mode. The image is a handful of RV32I words, so
this script encodes them directly and needs no toolchain.

Register contract (set through abstract register writes before each resume):
  a0  base address of the probe window, 64-byte aligned
  a1  store data
Result: t0, t1, t2, t3, t4 and t5 hold the six words loaded back from the
window, at offsets 0, 8, 16, 24, 32 and 40, and a2 holds their 32-bit sum.

Layout, as ICCM byte offsets:
  0x000  the probe: ten stores of every width, six loads, their sum, ebreak
  0x100  ebreak, the SEP_NMI_VEC reset target and the mtvec the test programs,
         so a bus-error trap also ends in debug mode

The hex is one byte per line from ICCM offset 0 after a comment header, the form
the bench TCM loader reads with $readmemh. ``--check`` fails when the committed
file differs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "sep_lsu_probe.itcm.hex"

A0, A1, A2, T0, T1, T2, T3, T4, T5 = 10, 11, 12, 5, 6, 7, 28, 29, 30
NMI_VECTOR_OFFSET = 0x100


def _store(width: int, rs2: int, rs1: int, imm: int) -> int:
    funct3 = {1: 0, 2: 1, 4: 2}[width]
    return (
        ((imm >> 5) & 0x7F) << 25
        | rs2 << 20
        | rs1 << 15
        | funct3 << 12
        | (imm & 0x1F) << 7
        | 0b0100011
    )


def _lw(rd: int, rs1: int, imm: int) -> int:
    return (imm & 0xFFF) << 20 | rs1 << 15 | 0b010 << 12 | rd << 7 | 0b0000011


def _add(rd: int, rs1: int, rs2: int) -> int:
    return rs2 << 20 | rs1 << 15 | rd << 7 | 0b0110011


FENCE = 0x0FF0_000F
EBREAK = 0x0010_0073

STORES = [(4, 8 * i) for i in range(8)] + [(2, 66), (1, 73)]
LOADS = [(T0, 0), (T1, 8), (T2, 16), (T3, 24), (T4, 32), (T5, 40)]


def program() -> list[int]:
    words = [_store(width, A1, A0, off) for width, off in STORES]
    words += [_lw(rd, A0, off) for rd, off in LOADS]
    words += [_add(A2, LOADS[0][0], LOADS[1][0])]
    words += [_add(A2, A2, rd) for rd, _ in LOADS[2:]]
    words += [FENCE, EBREAK]
    return words


def image() -> bytes:
    words = program()
    if 4 * len(words) > NMI_VECTOR_OFFSET:
        raise SystemExit("probe overruns the trap vector")
    words += [0] * (NMI_VECTOR_OFFSET // 4 - len(words)) + [EBREAK]
    return b"".join(w.to_bytes(4, "little") for w in words)


HEADER = (
    "// SPDX-License-Identifier: Apache-2.0\n"
    "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.\n"
    "// Output of gen_sep_lsu_probe_itcm.py: the SEP ICCM probe, one byte per line.\n"
)


def render() -> str:
    return HEADER + "".join(f"{b:02x}\n" for b in image())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed hex differs")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="ascii") != text:
            print(f"{OUT.name} is stale; rerun {Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="ascii")
    return 0


if __name__ == "__main__":
    sys.exit(main())
