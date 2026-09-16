#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Convert a byte-addressed Verilog hex to a 36-bit word/parity hex."""

import argparse
import re
import sys
from pathlib import Path

NOP = 0x00000013


def byte_odd_parity(byte_val: int) -> int:
    p = 0
    v = byte_val & 0xFF
    while v:
        p ^= 1
        v &= v - 1
    return p ^ 1


def word_parity(word: int) -> int:
    p = 0
    for i in range(4):
        p |= byte_odd_parity((word >> (i * 8)) & 0xFF) << i
    return p


def parse_verilog_hex(path: Path) -> dict[int, int]:
    mem: dict[int, int] = {}
    addr = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("@"):
                addr = int(line[1:], 16)
                continue
            for token in line.split():
                if re.fullmatch(r"[0-9A-Fa-f]{1,2}", token):
                    mem[addr] = int(token, 16)
                    addr += 1
    return mem


def build_words(byte_mem: dict[int, int], depth: int, default_word: int) -> list[int]:
    words = [default_word] * depth
    touched: set[int] = set()
    for byte_addr, byte_val in byte_mem.items():
        word_idx = byte_addr // 4
        byte_lane = byte_addr % 4
        if word_idx < depth:
            if word_idx not in touched:
                words[word_idx] = 0
                touched.add(word_idx)
            words[word_idx] |= (byte_val & 0xFF) << (byte_lane * 8)
    return words


def write_parhex(words: list[int], out_path: Path) -> None:
    with open(out_path, "w") as f:
        f.write("@00000000\n")
        for w in words:
            f.write(f"{((word_parity(w) << 32) | (w & 0xFFFFFFFF)):09X}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add byte-wise odd parity to a KM ROM hex file.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--depth",
        type=int,
        default=4096,
        help="ROM depth in words (default: 4096 = 16 KB, the key_manager ROM size)",
    )
    parser.add_argument("--default-word", type=lambda x: int(x, 0), default=NOP)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    write_parhex(
        build_words(parse_verilog_hex(args.input), args.depth, args.default_word), args.output
    )
    print(f"[add_rom_parity] {args.input} -> {args.output} ({args.depth} words)")


if __name__ == "__main__":
    main()
