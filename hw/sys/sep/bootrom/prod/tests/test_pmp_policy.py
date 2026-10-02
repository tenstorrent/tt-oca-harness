# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROD = Path(__file__).resolve().parents[1]
VECTOR = PROD / "src/vector.S"
HANDOFF = PROD / "src/rom_handoff.c"


def pmpaddr_values(source: str) -> dict[int, int]:
    matches = re.findall(
        r"\bli\s+t0,\s*(0x[0-9a-fA-F]+)[^\n]*\n\s*csrw\s+pmpaddr(\d+),\s*t0",
        source,
    )
    return {int(entry): int(value, 16) for value, entry in matches}


def decode_napot(value: int) -> tuple[int, int]:
    trailing_ones = 0
    bits = value
    while bits & 1:
        trailing_ones += 1
        bits >>= 1
    size = 1 << (trailing_ones + 3)
    base = (value & ~((1 << trailing_ones) - 1)) << 2
    return base, size


class PmpPolicyTest(unittest.TestCase):
    def test_cold_regions_match_the_boot_rom_address_map(self):
        values = pmpaddr_values(VECTOR.read_text())
        expected = {
            0: (0x10040000, 0x00010000),
            1: (0xC0040000, 0x00020000),
            3: (0x10000000, 0x00040000),
            4: (0x10800000, 0x00400000),
            5: (0xC0000000, 0x00040000),
            6: (0x40000000, 0x00800000),
        }
        self.assertEqual({entry: decode_napot(values[entry]) for entry in expected}, expected)

    def test_cold_policy_binds_machine_mode_and_keeps_bl1_regions_non_executable(self):
        source = VECTOR.read_text()
        rlb = source.index("li      t0, 0x4")
        first_locked_cfg = source.index("li      t0, 0x9b009b9d")
        mmwp = source.index("li      t0, 0x6")

        self.assertLess(rlb, first_locked_cfg)
        self.assertLess(first_locked_cfg, mmwp)
        self.assertEqual(source.count("csrw    0x747, t0"), 2)
        self.assertIn("li      t0, 0x009b9b9b", source)

    def test_handoff_releases_only_the_selected_bl1_region(self):
        source = HANDOFF.read_text()
        release = source.index("pmp_release_bl1(bl1_in_iccm)")
        jump = source.index("jump_to_bl1(entry_addr)")

        self.assertLess(release, jump)
        self.assertIn('"csrs pmpcfg0, %0"', source)
        self.assertIn('"csrs pmpcfg1, %0"', source)


if __name__ == "__main__":
    unittest.main()
