#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse

_ROCKET_ECC_MASKS = (
    0xAB55555556AAAD5B,
    0xCD9999999B33366D,
    0xF1E1E1E1E3C3C78E,
    0x01FE01FE03FC07F0,
    0x01FFFE0003FFF800,
    0x01FFFFFFFC000000,
    0xFE00000000000000,
)


def _parity(value: int) -> int:
    parity = 0
    while value:
        parity ^= value & 1
        value >>= 1
    return parity


def _rocket_ecc_72(data: int) -> int:
    """Pack one 64-bit word with Rocket SECDED bits in [71:64]."""
    check_bits = [_parity(data & mask) for mask in _ROCKET_ECC_MASKS]
    overall = _parity(data) ^ (sum(check_bits) & 1)
    ecc = overall << 7
    for index, bit in enumerate(check_bits):
        ecc |= bit << index
    return (ecc << 64) | data


def write_verilog(in_file: str, out_file: str, data_width: int) -> None:
    data = open(in_file, "rb").read()
    with open(out_file, "w") as file:
        file.write("@0\n")
        if data_width == 64:
            # One 64-bit little-endian word per line: the ROM/SRAM memories are
            # 64-bit wide and $readmemh fills one word per line. Zero-pad a
            # trailing partial word.
            for i in range(0, len(data), 8):
                word = data[i : i + 8].ljust(8, b"\x00")
                file.write(f"{int.from_bytes(word, 'little'):016x}\n")
        elif data_width == 8:
            for byte in data:
                file.write(f"{byte:02x}\n")
        elif data_width == 1:
            file.writelines(f"{(byte >> bit) & 1:x}\n" for byte in data for bit in range(7, -1, -1))
        elif data_width == 72:
            chunks = (data[offset : offset + 8] for offset in range(0, len(data), 8))
            words = (int.from_bytes(chunk.ljust(8, b"\0"), byteorder="little") for chunk in chunks)
            file.writelines(f"{_rocket_ecc_72(word):018x}\n" for word in words)
        else:
            raise ValueError(f"unsupported data width {data_width}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a binary image to a Verilog memory file.")
    parser.add_argument("in_file")
    parser.add_argument("--out_file", required=True)
    parser.add_argument("--data_width", type=int, choices=(1, 8, 64, 72), required=True)
    args = parser.parse_args()

    write_verilog(args.in_file, args.out_file, args.data_width)


if __name__ == "__main__":
    main()
