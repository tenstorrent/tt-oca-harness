#!/usr/bin/env python3
"""Generate the expected CRC-8/ROHC and CRC-32C values used by test_rom_crc.c.

This is an independent software model of the two CRC modes the hardware
implements in rtl/km_crc_engine.sv (CRC8_ROHC_POLY 0xE0, CRC32C_POLY 0x82F63B78),
which firmware reaches through the PCPI custom instructions wrapped by
drivers/rom_crc.c. Deriving the vectors here rather than from rom_crc.c is the
point: the test compares hardware results against values this model produced, so
the model must not share an implementation with the thing under test.

Both CRCs are computed, then checked against the published golden values before
anything is printed, so a mismatch fails loudly instead of emitting bad vectors.
Output is C-style (0xD0u, 0xE3069283u) for copy-paste into the test.

Developer helper only -- no build target depends on it.

Usage: python3 scripts/gen_crc_vectors.py
"""

import sys

# CRC-8/ROHC: reflected poly 0xE0, init 0xFF, XorOut 0x00.
CRC8_ROHC_POLY = 0xE0
# CRC-32C (Castagnoli): reflected poly 0x82F63B78, init/XorOut 0xFFFFFFFF.
CRC32C_POLY = 0x82F63B78


def _reflected_table(poly: int, width_mask: int) -> list:
    """Byte-wise table for a reflected CRC, as the engine's shift form implies."""
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ (poly if crc & 1 else 0)
        table.append(crc & width_mask)
    return table


CRC8_TABLE = _reflected_table(CRC8_ROHC_POLY, 0xFF)
CRC32C_TABLE = _reflected_table(CRC32C_POLY, 0xFFFFFFFF)


def crc8_rohc(data: bytes) -> int:
    """CRC-8/ROHC: init 0xFF, XorOut 0x00."""
    crc = 0xFF
    for b in data:
        crc = CRC8_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFF


def crc32c(data: bytes) -> int:
    """CRC-32C Castagnoli: init 0xFFFFFFFF, XorOut 0xFFFFFFFF."""
    crc = 0xFFFFFFFF
    for b in data:
        crc = (crc >> 8) ^ CRC32C_TABLE[(crc ^ b) & 0xFF]
    return crc ^ 0xFFFFFFFF


CRC8_CASES = [
    ("empty", b""),
    ("single 0x00", bytes([0x00])),
    ("single 0xFF", bytes([0xFF])),
    ("123456789", b"123456789"),
    ("a", b"a"),
    ("ab", b"ab"),
    ("abc", b"abc"),
    ("zero 4B", bytes(4)),
    ("0xFF 4B", bytes([0xFF] * 4)),
]

# Independently published CRC-32C values (Go hash/crc32 golden tests), used to
# confirm this model agrees with the standard before the vectors are trusted.
CRC32C_GOLDEN = [
    ("", 0x00000000),
    ("a", 0xC1D04330),
    ("ab", 0xE2A22936),
    ("abc", 0x364B3FB7),
    ("abcd", 0x92C80A31),
    ("abcde", 0xC450D697),
    ("abcdef", 0x53BCEFF1),
    ("abcdefg", 0xE627F441),
    ("abcdefgh", 0x0A9421B7),
    ("abcdefghi", 0x2DDC99FC),
    ("123456789", 0xE3069283),
    ("The quick brown fox jumps over the lazy dog", 0x22620404),
]

# CRC-8/ROHC check value: the standard's published CRC of "123456789".
CRC8_ROHC_CHECK = 0xD0


def _self_check() -> int:
    failures = 0
    got = crc8_rohc(b"123456789")
    if got != CRC8_ROHC_CHECK:
        print(f"CRC-8/ROHC check value mismatch: got 0x{got:02X}, "
              f"want 0x{CRC8_ROHC_CHECK:02X}", file=sys.stderr)
        failures += 1
    for s, want in CRC32C_GOLDEN:
        got = crc32c(s.encode())
        if got != want:
            print(f"CRC-32C mismatch for {s!r}: got 0x{got:08X}, want 0x{want:08X}",
                  file=sys.stderr)
            failures += 1
    return failures


def main() -> int:
    if _self_check():
        print("refusing to emit vectors: model disagrees with published values",
              file=sys.stderr)
        return 1

    print("/* CRC-8/ROHC (init 0xFF, XorOut 0x00) - from gen_crc_vectors.py */")
    for name, data in CRC8_CASES:
        print(f"  /* {name} */ 0x{crc8_rohc(data):02X}u,")

    print("\n/* CRC-32C Castagnoli - from gen_crc_vectors.py, "
          "cross-checked against Go hash/crc32 */")
    for s, _ in CRC32C_GOLDEN:
        name = repr(s) if len(s) <= 12 else s[:20] + "..."
        print(f"  /* {name} */ 0x{crc32c(s.encode()):08X}u,")
    return 0


if __name__ == "__main__":
    sys.exit(main())
