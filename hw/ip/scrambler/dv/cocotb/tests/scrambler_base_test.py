# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the scrambler family IP-level cocotb tests.

``scrambler_tb_top`` instantiates every sized variant in both BYTE_WISE modes
behind pin bundles named ``<mode><depth>_*`` (``w`` for word mode, ``b`` for
byte-wise mode). The scrambler is combinational: the bench drives the pins of
one instance, lets a nanosecond pass, and samples its outputs, so no clock is
involved.

The contract under test (rtl/scrambler.sv): the scrambled address is a
permutation of the address space for a given key; a word scrambled at an
address descrambles back to itself at the same address and key; and in
byte-wise mode each byte lane scrambles independently, so a memory that
merges byte-masked writes keeps every lane descramblable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from cocotb.triggers import Timer

SETTLE_NS = 1
DATA_WIDTH = 32
DATA_MASK = (1 << DATA_WIDTH) - 1
NUM_LANES = DATA_WIDTH // 8
FULL_MASK = (1 << NUM_LANES) - 1


@dataclass(frozen=True)
class Variant:
    """One instance of the family: its pin prefix, address width and mode."""

    depth: int
    addr_width: int
    byte_wise: bool

    @property
    def prefix(self) -> str:
        return f"{'b' if self.byte_wise else 'w'}{self.depth}"

    @property
    def name(self) -> str:
        return f"scrambler_{self.depth}x32 BYTE_WISE={int(self.byte_wise)}"


DEPTHS = ((512, 9), (1024, 10), (2048, 11), (4096, 12), (8192, 13))
VARIANTS = tuple(
    Variant(depth, width, byte_wise) for depth, width in DEPTHS for byte_wise in (False, True)
)
WORD_VARIANTS = tuple(v for v in VARIANTS if not v.byte_wise)
BYTEWISE_VARIANTS = tuple(v for v in VARIANTS if v.byte_wise)


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def merge_lanes(old: int, new: int, mask: int) -> int:
    """The word a byte-maskable memory holds after writing ``new`` under ``mask`` over ``old``."""
    merged = 0
    for lane in range(NUM_LANES):
        source = new if (mask >> lane) & 1 else old
        merged |= source & (0xFF << (8 * lane))
    return merged


class ScramblerPort:
    """Pin-level access to one instance of the family."""

    def __init__(self, dut, variant: Variant) -> None:
        self.dut = dut
        self.variant = variant
        self.log = logging.getLogger(f"cocotb.tb.{variant.prefix}")
        p = variant.prefix
        self.addr = getattr(dut, f"{p}_addr")
        self.byte_mask = getattr(dut, f"{p}_byte_mask")
        self.key = getattr(dut, f"{p}_key")
        self.write_data = getattr(dut, f"{p}_write_data")
        self.scrambled_read_data = getattr(dut, f"{p}_scrambled_read_data")
        self.scrambled_addr = getattr(dut, f"{p}_scrambled_addr")
        self.scrambled_write_data = getattr(dut, f"{p}_scrambled_write_data")
        self.read_data = getattr(dut, f"{p}_read_data")

    def init(self, key: int) -> None:
        self.addr.value = 0
        self.byte_mask.value = FULL_MASK
        self.key.value = key
        self.write_data.value = 0
        self.scrambled_read_data.value = 0

    async def scramble(self, addr: int, data: int, mask: int = FULL_MASK) -> tuple[int, int]:
        """Drive an address and write word; return (scrambled address, scrambled word)."""
        self.addr.value = addr
        self.byte_mask.value = mask
        self.write_data.value = data
        await Timer(SETTLE_NS, "ns")
        return int(self.scrambled_addr.value), int(self.scrambled_write_data.value)

    async def scrambled_address(self, addr: int) -> int:
        self.addr.value = addr
        await Timer(SETTLE_NS, "ns")
        return int(self.scrambled_addr.value)

    async def descramble(self, addr: int, scrambled_word: int) -> int:
        """Drive an address and the word read from memory; return the descrambled word."""
        self.addr.value = addr
        self.scrambled_read_data.value = scrambled_word
        await Timer(SETTLE_NS, "ns")
        return int(self.read_data.value)


__all__ = [
    "BYTEWISE_VARIANTS",
    "DATA_MASK",
    "DATA_WIDTH",
    "FULL_MASK",
    "NUM_LANES",
    "VARIANTS",
    "WORD_VARIANTS",
    "ScramblerPort",
    "Variant",
    "merge_lanes",
    "random_seed",
]
