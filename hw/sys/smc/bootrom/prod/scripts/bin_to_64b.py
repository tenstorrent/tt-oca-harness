# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#!/usr/bin/env python3
"""
Convert a raw binary (.bin) into a text file with one 64-bit binary string per line.

Semantics:
- Read bytes in file order (ascending memory addresses).
- Pack each group of 8 bytes into a little-endian 64-bit word:
  word = b0 | (b1<<8) | ... | (b7<<56)
- Print each word as 64 binary digits (MSB on the left).
- If the input size is not a multiple of 8, the remaining high bytes are zero.

Usage:
  python3 bin_to_64b.py --input in.bin --output out.bin64
"""

import argparse
import pathlib
import sys


def convert_bin_to_64b_lines(data: bytes) -> list[str]:
    lines: list[str] = []
    i = 0
    n = len(data)
    while i < n:
        # Low byte first (little-endian)
        b0 = data[i]
        b1 = data[i + 1] if i + 1 < n else 0
        b2 = data[i + 2] if i + 2 < n else 0
        b3 = data[i + 3] if i + 3 < n else 0
        b4 = data[i + 4] if i + 4 < n else 0
        b5 = data[i + 5] if i + 5 < n else 0
        b6 = data[i + 6] if i + 6 < n else 0
        b7 = data[i + 7] if i + 7 < n else 0
        word = (
            (b0 & 0xFF)
            | ((b1 & 0xFF) << 8)
            | ((b2 & 0xFF) << 16)
            | ((b3 & 0xFF) << 24)
            | ((b4 & 0xFF) << 32)
            | ((b5 & 0xFF) << 40)
            | ((b6 & 0xFF) << 48)
            | ((b7 & 0xFF) << 56)
        )
        lines.append(f"{word:064b}")
        i += 8
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert raw binary to 64-bit-per-line binary text (LE pack, MSB-left)"
    )
    ap.add_argument("--input", required=True, help="Path to input raw binary (.bin)")
    ap.add_argument("--output", required=True, help="Path to output text file (.bin64)")
    args = ap.parse_args()

    in_path = pathlib.Path(args.input)
    out_path = pathlib.Path(args.output)
    if not in_path.exists():
        print(f"Error: input file not found: {in_path}", file=sys.stderr)
        return 2

    data = in_path.read_bytes()
    lines = convert_bin_to_64b_lines(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    print(f"Wrote {len(lines)} lines to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
