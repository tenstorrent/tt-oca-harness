#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse


def write_verilog(in_file: str, out_file: str, data_width: int) -> None:
    data = open(in_file, "rb").read()
    with open(out_file, "w") as file:
        file.write("@0\n")
        if data_width == 64:
            # One 64-bit little-endian word per line. The ROM/SRAM memories are
            # 64-bit wide, so $readmemh fills one word per line; packing a single
            # byte per line (data_width 8) would scatter each byte into its own
            # word and corrupt the image. Zero-pad a trailing partial word.
            for i in range(0, len(data), 8):
                word = data[i : i + 8].ljust(8, b"\x00")
                file.write(f"{int.from_bytes(word, 'little'):016x}\n")
        elif data_width == 8:
            for byte in data:
                file.write(f"{byte:02x}\n")
        elif data_width == 1:
            for byte in data:
                for bit in range(7, -1, -1):
                    file.write(f"{(byte >> bit) & 1:x}\n")
        else:
            raise ValueError(f"unsupported data width {data_width}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a binary image to a Verilog memory file.")
    parser.add_argument("in_file")
    parser.add_argument("--out_file", required=True)
    parser.add_argument("--data_width", type=int, choices=(1, 8, 64), required=True)
    args = parser.parse_args()

    write_verilog(args.in_file, args.out_file, args.data_width)


if __name__ == "__main__":
    main()
