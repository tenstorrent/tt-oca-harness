#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

import argparse


def write_verilog(in_file: str, out_file: str, data_width: int) -> None:
    data = open(in_file, "rb").read()
    with open(out_file, "w") as file:
        file.write("@0\n")
        if data_width == 8:
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
    parser.add_argument("--data_width", type=int, choices=(1, 8), required=True)
    args = parser.parse_args()

    write_verilog(args.in_file, args.out_file, args.data_width)


if __name__ == "__main__":
    main()
