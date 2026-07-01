#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse
import re


def replace_offsets_in_hex_file(in_file: str, out_file: str, start_addr: int) -> None:
    with open(in_file) as file:
        lines = file.readlines()

    pattern = re.compile(r"@([0-9A-Fa-f]+)")
    addr_offset = None
    new_lines = []
    for line in lines:
        match = pattern.search(line)
        if match:
            hex_string = match.group(1)
            hex_number = int(hex_string, 16)
            if addr_offset is None:
                addr_offset = hex_number - start_addr
            updated_number = hex_number - addr_offset
            if updated_number < 0:
                raise RuntimeError(
                    f"Attempted to apply offset {addr_offset} to address {hex_string}, "
                    "which results in a negative address"
                )
            line = pattern.sub(f"@{updated_number:X}", line)
        new_lines.append(line)

    with open(out_file, "w") as file:
        file.writelines(new_lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adjust SMC FW hex addresses from system address to preload address."
    )
    parser.add_argument("in_file")
    parser.add_argument("--out_file")
    parser.add_argument("--start_addr", default="0")
    args = parser.parse_args()

    start_addr = int(args.start_addr, 0)
    replace_offsets_in_hex_file(args.in_file, args.out_file or args.in_file, start_addr)


if __name__ == "__main__":
    main()
