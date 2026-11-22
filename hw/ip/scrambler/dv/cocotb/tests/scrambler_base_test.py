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

The data cipher model below follows ``hw/ip/scrambler/doc/architecture.adoc``
alone: the round key is the address expansion XOR the key, the write word is
XORed with it, each nibble passes the PRESENT S-box, and the word passes the
player permutation. Byte-wise mode replaces the player with a per-byte
``perm8`` whose bit table the document does not give, so the model stops at
the S-box layer there. The address scramble tables (``sbox3``, ``permN``) are
not in the document either, and no model covers the scrambled address.
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


# architecture.adoc "SRAM scrambler S-box" table: S(x) for x = 0x0 .. 0xF.
SBOX4 = (0xC, 0x5, 0x6, 0xB, 0x9, 0x0, 0xA, 0xD, 0x3, 0xE, 0xF, 0x8, 0x4, 0x7, 0x1, 0x2)

# architecture.adoc "SRAM scrambler permutation" tables: input bit i -> output bit P(i).
PLAYER = dict(
    zip(
        range(31, -1, -1),
        (0, 4, 8, 12, 16, 20, 24, 28, 1, 5, 9, 13, 17, 21, 25, 29)
        + (2, 6, 10, 14, 18, 22, 26, 30, 3, 7, 11, 15, 19, 23, 27, 31),
    )
)

# architecture.adoc "SRAM scrambler address expansion" table: ADDR_WIDTH ->
# (whole address copies, high bit and low bit of the trailing slice), MSB first.
ADDR_EXPANSION = {
    9: (3, 8, 4),
    10: (3, 9, 8),
    11: (2, 10, 1),
    12: (2, 11, 4),
    13: (2, 12, 7),
}


def expand_address(addr: int, addr_width: int) -> int:
    """The 32-bit address expansion of the address expansion table."""
    copies, high, low = ADDR_EXPANSION[addr_width]
    expanded = 0
    for _ in range(copies):
        expanded = (expanded << addr_width) | addr
    tail_width = high - low + 1
    expanded = (expanded << tail_width) | ((addr >> low) & ((1 << tail_width) - 1))
    assert copies * addr_width + tail_width == DATA_WIDTH
    return expanded


def model_round_key(key: int, addr: int, addr_width: int) -> int:
    """Rkey = scrambler_key ^ expanded address (architecture.adoc Address Tweaking)."""
    return (key ^ expand_address(addr, addr_width)) & DATA_MASK


def model_sbox_layer(word: int) -> int:
    """Each of the eight nibbles of ``word`` through the S-box, in place."""
    out = 0
    for lane in range(DATA_WIDTH // 4):
        out |= SBOX4[(word >> (4 * lane)) & 0xF] << (4 * lane)
    return out


def model_player(word: int) -> int:
    """Output bit P(i) takes input bit i."""
    out = 0
    for src, dst in PLAYER.items():
        out |= ((word >> src) & 1) << dst
    return out


def model_scramble_pre_perm(key: int, addr: int, data: int, addr_width: int) -> int:
    """The S-box layer output for ``data`` written at ``addr`` (Scrambling Procedure)."""
    return model_sbox_layer((data ^ model_round_key(key, addr, addr_width)) & DATA_MASK)


def model_scramble_word(key: int, addr: int, data: int, addr_width: int) -> int:
    """The word-mode scrambled write data: player(S(data ^ Rkey))."""
    return model_player(model_scramble_pre_perm(key, addr, data, addr_width))


def byte_popcounts(word: int) -> tuple[int, ...]:
    """Population count of each byte lane, lane 0 first."""
    return tuple(bin((word >> (8 * lane)) & 0xFF).count("1") for lane in range(NUM_LANES))


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
    "ADDR_EXPANSION",
    "BYTEWISE_VARIANTS",
    "DATA_MASK",
    "DATA_WIDTH",
    "FULL_MASK",
    "NUM_LANES",
    "PLAYER",
    "SBOX4",
    "VARIANTS",
    "WORD_VARIANTS",
    "ScramblerPort",
    "Variant",
    "byte_popcounts",
    "expand_address",
    "merge_lanes",
    "model_player",
    "model_round_key",
    "model_sbox_layer",
    "model_scramble_pre_perm",
    "model_scramble_word",
    "random_seed",
]
