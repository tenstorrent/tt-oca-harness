# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SRAM datapath-breadth config + driver for ``sep_sram_datapath_breadth_test``.

`[RANDCFG]` rep: ``SepSramBreadthCfg`` is the single source of truth for BOTH the
DUT programming AND the golden/checker expectations. Required coverage cells are
walked deterministically (so a single seed never skips one); only legal knobs
(mask order, region offsets, write/init data, the sequential-window length) are
seed-randomized, with masked values so they read back exactly.

The SRAM port is 64-bit single-beat (AXI4-Lite-like; the reference suite "burst" tests are
audit-only AWLEN=0/ARLEN=0 -- no multi-beat burst feature), so only single-beat
accesses are issued. ``length`` selects the byte count: 8 = full 64-bit word,
1..7 = a sub-word write/read whose WSTRB cocotbext-axi derives from addr+length.

WSTRB coverage note: cocotbext-axi ``init_write`` has no explicit-strobe argument
-- it derives the strobe from address+length, so only CONTIGUOUS byte runs are
expressible. This rep walks all 36 contiguous masks (all 8 one-hot lanes + every
contiguous multi-byte run). Arbitrary NON-contiguous masks (e.g. 0x05) are NOT
expressible without a lower-level explicit-strobe write.
WSTRB=0x00 (all-zero strobe) is excluded (undefined per the SRAM spec).
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

# SEP SRAM aperture (256 KiB). Derived from the generated Python register export
# rather than a literal, so a map change surfaces as an import error instead of a
# silently stale constant. The C header spells the same aperture
# SEP_TOP_SEP_SRAM_BASE_ADDR / _SIZE in sep_addr.h, but only the Python export
# is importable from here.
SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
_MASK64 = 0xFFFF_FFFF_FFFF_FFFF

_WORD_BITS = 64

# Walking one and walking zero: every one of the 64 bit positions, one word each.
WALKING_ONE_PATTERNS = [1 << bit for bit in range(_WORD_BITS)]
WALKING_ZERO_PATTERNS = [_MASK64 ^ (1 << bit) for bit in range(_WORD_BITS)]

# Required data patterns (always present; the RANDCFG adds seed-random extras).
_REQUIRED_PATTERNS = [
    0xAAAA_AAAA_AAAA_AAAA,
    0x5555_5555_5555_5555,
    *WALKING_ONE_PATTERNS,
    *WALKING_ZERO_PATTERNS,
    0xDEAD_BEEF_CAFE_BABE,
]


# Floors the test asserts, so a generator or list that shrank fails the run
# rather than reporting a clean pass over fewer cells.
CONTIGUOUS_WSTRB_SPECS = 36  # 8 one-hot + 28 multi-byte runs on an 8-byte lane
WALKING_POSITIONS = 64  # one walking-one and one walking-zero word per data bit


def _contiguous_wstrb_specs() -> list[tuple[int, int]]:
    """All (offset, length) contiguous byte runs on the 8-byte SRAM lane; the WSTRB
    mask is ((1<<length)-1) << offset. 36 specs total (8 one-hot + 28 multi-byte)."""
    specs = []
    for length in range(1, 9):
        for offset in range(0, 9 - length):
            specs.append((offset, length))
    return specs


class SepSramBreadthCfg:
    """Single source of truth for the SRAM breadth stimulus + golden expectations."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.base_addr = SEP_SRAM_BASE
        self.size = SEP_SRAM_SIZE

        # WSTRB: all 36 contiguous masks REQUIRED (deterministic), order shuffled;
        # the init word and per-mask new-data are seed-random (masked to 64b).
        self.wstrb_specs = _contiguous_wstrb_specs()
        # Construction invariant, in the same spirit as the inbound START/END
        # count: the 8-byte lane has exactly 36 contiguous runs, so a generator
        # change is a config bug and must not reach the bench as a smaller sweep.
        if len(self.wstrb_specs) != CONTIGUOUS_WSTRB_SPECS:
            raise RuntimeError(
                f"contiguous WSTRB set is {len(self.wstrb_specs)}, "
                f"expected {CONTIGUOUS_WSTRB_SPECS} on an 8-byte lane"
            )
        rng.shuffle(self.wstrb_specs)
        self.wstrb_offset = self._aligned(rng, 0x1000, 0x2000)
        self.wstrb_init = rng.getrandbits(64)
        self.wstrb_newdata = [rng.getrandbits(64) for _ in self.wstrb_specs]

        # Patterns: the required cells are always present; add a few seed-random extras.
        # Each walk covers all 64 bit positions exactly once; a shorter walk is a
        # config bug and must not reach the bench as a narrower CHK-PATTERN.
        for name, walk in (
            ("walking-one", WALKING_ONE_PATTERNS),
            ("walking-zero", WALKING_ZERO_PATTERNS),
        ):
            if len(set(walk)) != WALKING_POSITIONS:
                raise RuntimeError(
                    f"{name} set has {len(set(walk))} distinct words, "
                    f"expected {WALKING_POSITIONS} on a 64-bit word"
                )
        n_extra = rng.randrange(2, 5)
        self.pattern_values = list(_REQUIRED_PATTERNS) + [
            rng.getrandbits(64) for _ in range(n_extra)
        ]
        self.pattern_offset = self._aligned(rng, 0x2000, 0x3000)

        # Boundary: always the base word and the top valid 64-bit word.
        self.boundary_addrs = [self.base_addr, self.base_addr + self.size - 8]

        # Sequential: >= 4 words (seed-bounded), random aligned base + seed data.
        self.seq_words = rng.randrange(4, 9)
        self.seq_offset = self._aligned(rng, 0x3000, 0x3F00)
        self.seq_seed = rng.getrandbits(64)

        # Non-vacuity: two adjacent words written with complementary patterns.
        self.nonvac_wr_offset = self._aligned(rng, 0x4000, 0x5000)
        self.nonvac_rd_offset = self.nonvac_wr_offset + 8
        self.nonvac_pattern = rng.getrandbits(64)

    @staticmethod
    def _aligned(rng: SepSeededRng, lo: int, hi: int) -> int:
        """A 64-bit-word-aligned offset in [lo, hi)."""
        return rng.randrange(lo, hi) & ~0x7

    def summary(self) -> str:
        b = self.base_addr
        return (
            f"seed={self.seed} wstrb_masks={len(self.wstrb_specs)} (all contiguous; "
            f"non-contiguous not walked) wstrb@0x{b + self.wstrb_offset:08x} "
            f"patterns={len(self.pattern_values)} pat@0x{b + self.pattern_offset:08x} "
            f"seq_words={self.seq_words} seq@0x{b + self.seq_offset:08x} "
            f"boundary=[0x{self.boundary_addrs[0]:08x},0x{self.boundary_addrs[1]:08x}]"
        )


class SepSramBreadth:
    """Single-beat SRAM read/write over the CPU-LSU AXI splice + WSTRB golden."""

    def __init__(self, test, cfg: SepSramBreadthCfg) -> None:
        self.test = test
        self.cfg = cfg

    async def write(self, addr: int, data: int, length: int = 8) -> None:
        seq = SepAxiAccessSeq(
            f"sram_wr_0x{addr:08x}_l{length}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=length,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SRAM write @0x{addr:08x} len{length} not OKAY")

    async def read(self, addr: int, length: int = 8) -> int:
        seq = SepAxiAccessSeq(
            f"sram_rd_0x{addr:08x}_l{length}",
            op=SepAxiOp.READ,
            addr=addr,
            length=length,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SRAM read @0x{addr:08x} len{length} not OKAY")
        return seq.rdata

    @staticmethod
    def apply_wstrb(old: int, newdata: int, offset: int, length: int) -> int:
        """Golden: a WSTRB write of ``length`` bytes of ``newdata`` at byte ``offset``
        replaces only those byte lanes of ``old`` (computed independently of the DUT)."""
        result = old
        for i in range(length):
            byte = (newdata >> (8 * i)) & 0xFF
            pos = 8 * (offset + i)
            result = (result & ~(0xFF << pos)) | (byte << pos)
        return result & _MASK64
