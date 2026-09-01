# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Convert a raw little-endian RV32 binary into the KM ROM .parhex format.

Each output line is 9 hex digits: {word_parity[3:0]}{instr[31:0]}. word_parity
matches the KM ROM backdoor fill in tb_backdoor_mem (tb/tb_top.sv,
bd_km_word_parity): per-byte ODD parity (bit i = ~^byte_i)."""

import sys


def word_parity(w: int) -> int:
    p = 0
    for i in range(4):
        b = (w >> (8 * i)) & 0xFF
        odd = 1 ^ (bin(b).count("1") & 1)  # ~^b : 1 when byte has even #ones
        p |= odd << i
    return p


data = open(sys.argv[1], "rb").read()
if len(data) % 4:
    data += b"\x00" * (4 - len(data) % 4)
print("@00000000")
for i in range(0, len(data), 4):
    w = int.from_bytes(data[i : i + 4], "little")
    print(f"{word_parity(w):X}{w:08X}")
