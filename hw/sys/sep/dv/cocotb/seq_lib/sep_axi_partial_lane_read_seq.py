# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Partial-lane read config + driver for ``sep_axi_partial_lane_read_test``.

A read narrower than the 64-bit CPU-LSU beat only obligates the responder to
drive the addressed byte lanes: a 32-bit CSR endpoint leaves RDATA[63:32]
undriven, and a narrow-ARSIZE beat leaves every non-addressed lane undriven.
The VIP master samples the FULL beat and extracts the addressed bytes, so the
value a test receives must be a pure function of the addressed lanes — exact
against an independent golden and identical on re-read — regardless of what
the undriven lanes carry. This rep pins that contract through the public VIP
read path alone (no cocotb/cocotbext global state involved).

`[RANDCFG]` rep: ``SepAxiPartialLaneReadCfg`` is the single source of truth
for the stimulus AND the golden expectations. Required coverage cells are
walked deterministically (all 36 contiguous byte-run slices of a 64-bit word;
all 14 aligned narrow-ARSIZE cells; the all-zeros/all-ones CSR patterns);
only legal knobs (walk order, SRAM offsets, data values, extra CSR patterns)
are seed-randomized.

Each read — CSR, byte-run slice, and narrow-ARSIZE — runs twice with a
disturbing read of an unrelated value in between, so a result that depends
on leftover channel state instead of the addressed lanes shows up as a
repeat mismatch.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import SEP_CPU_CTRL, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SEP_CPU_CTRL_BASE = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")
SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")

# Full 32-bit RW scratch register with no side effects (same target the AXI
# smoke write/readback uses); CSR spacing is 64-bit, so a 4-byte read here
# obligates only RDATA[31:0].
SW_DEBUG_ADDR = SEP_CPU_CTRL.addr("SEP_SW_DEBUG")

# Non-zero RO register used as the disturbing read between CSR repeats; its
# value is also checked, so the disturbance itself is evidence.
LOCAL_BASE_ADDR_ADDR = SEP_CPU_CTRL.addr("SEP_LOCAL_BASE_ADDR")
LOCAL_BASE_ADDR_EXP = SEP_CPU_CTRL.reset32("SEP_LOCAL_BASE_ADDR")

_MASK64 = 0xFFFF_FFFF_FFFF_FFFF

# Combinatorial floors for an 8-byte beat. The walk tally is held against
# these, not against len() of the list that drove it, so a walk that drops
# a cell fails rather than shrinking the bound.
SLICE_CELL_FLOOR = sum(range(1, 9))  # 8+7+…+1 = 36
ARSIZE_CELL_FLOOR = 8 + 4 + 2  # AxSIZE 0/1/2, aligned offsets only

# CSR patterns that must run on every seed: the two extremes a lane-extraction
# defect is most likely to alias with (all-zeros looks like an undriven-lane
# fill; all-ones looks like a sign/width spill).
_REQUIRED_CSR_PATTERNS = [0x0000_0000, 0xFFFF_FFFF]


def _slice_specs() -> list[tuple[int, int]]:
    """All (offset, length) contiguous byte runs of an 8-byte beat (36 total)."""
    return [(offset, length) for length in range(1, 9) for offset in range(0, 9 - length)]


def _arsize_specs() -> list[tuple[int, int]]:
    """All aligned (size, offset) narrow-ARSIZE cells on an 8-byte beat.

    AxSIZE 0/1/2 at every legal aligned lane offset: 8 + 4 + 2 = 14 cells. The
    full-width AxSIZE=3 beat is the slice walk's baseline, not repeated here.
    """
    return [(size, offset) for size in (0, 1, 2) for offset in range(0, 8, 1 << size)]


class SepAxiPartialLaneReadCfg:
    """Single source of truth for the partial-lane-read stimulus + goldens."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)

        # CSR repeats: required extremes always present, plus seed-random extras.
        n_extra = rng.randrange(2, 5)
        self.csr_patterns = list(_REQUIRED_CSR_PATTERNS) + [
            rng.getrandbits(32) for _ in range(n_extra)
        ]

        # SRAM word under test and its disturb neighbor (complement, so a read
        # that leaks the neighbor's lanes cannot match the golden).
        self.sram_addr = SEP_SRAM_BASE + (rng.randrange(0x5000, 0x6000) & ~0x7)
        self.word = rng.getrandbits(64)
        self.disturb_addr = self.sram_addr + 8
        self.disturb_word = (~self.word) & _MASK64

        # Required cells walked deterministically, order seed-shuffled.
        self.slice_specs = _slice_specs()
        rng.shuffle(self.slice_specs)
        self.arsize_specs = _arsize_specs()
        rng.shuffle(self.arsize_specs)

    def slice_golden(self, offset: int, length: int) -> int:
        """Expected value of a ``length``-byte read at byte ``offset`` of the word."""
        return (self.word >> (8 * offset)) & ((1 << (8 * length)) - 1)

    def summary(self) -> str:
        return (
            f"seed={self.seed} csr_patterns={len(self.csr_patterns)} "
            f"sw_debug@0x{SW_DEBUG_ADDR:08x} word=0x{self.word:016x} "
            f"@0x{self.sram_addr:08x} slices={len(self.slice_specs)} "
            f"arsize_cells={len(self.arsize_specs)}"
        )


class SepAxiPartialLaneRead:
    """Single-beat reads/writes over the CPU-LSU AXI splice for the lane rep."""

    def __init__(self, test) -> None:
        self.test = test

    async def write(self, addr: int, data: int, length: int) -> None:
        seq = SepAxiAccessSeq(
            f"lane_wr_0x{addr:08x}_l{length}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=length,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"lane write @0x{addr:08x} len{length} not OKAY")

    async def read(self, addr: int, length: int, *, size: int | None = None) -> int:
        seq = SepAxiAccessSeq(
            f"lane_rd_0x{addr:08x}_l{length}",
            op=SepAxiOp.READ,
            addr=addr,
            length=length,
            size=size,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"lane read @0x{addr:08x} len{length} size={size} not OKAY")
        return seq.rdata


def _selftest() -> None:
    assert len(_slice_specs()) == SLICE_CELL_FLOOR, (
        f"slice cell list drifted: {len(_slice_specs())} != {SLICE_CELL_FLOOR}"
    )
    assert len(_arsize_specs()) == ARSIZE_CELL_FLOOR, (
        f"ARSIZE cell list drifted: {len(_arsize_specs())} != {ARSIZE_CELL_FLOOR}"
    )


_selftest()
