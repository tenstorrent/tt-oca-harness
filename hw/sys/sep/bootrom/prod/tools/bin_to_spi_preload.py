#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Convert a raw binary file to Verilog $readmemh hex format (.spi_preload).

Usage: python3 bin_to_spi_preload.py input.bin output.spi_preload
"""

import sys


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.bin> <output.spi_preload>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "rb") as f:
        data = f.read()

    with open(sys.argv[2], "w") as f:
        f.write("@00000000\n")
        for i in range(0, len(data), 8):
            chunk = data[i : i + 8]
            f.write(" ".join(f"{b:02X}" for b in chunk) + "\n")

    print(f"Converted {len(data)} bytes to {sys.argv[2]}", file=sys.stderr)


if __name__ == "__main__":
    main()
