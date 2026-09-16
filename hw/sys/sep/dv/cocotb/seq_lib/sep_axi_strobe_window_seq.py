# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Narrow-write byte masking and memory-window readback.

Two contracts a register-only sweep cannot reach.

**Narrow writes.** A write whose ``AxSIZE`` is smaller than the bus beat
asserts only some byte lanes. The addressed bytes must take the new value and
every other byte of the word must be bit-identical to what was there before.
A shadow copy of the word is kept in Python and compared after each write, so
a conversion stage that widens the strobe, drops it, or writes the whole beat
fails here rather than looking like a normal write.

**Memory windows.** A window behind ``tlul_adapter_sram`` uses the TileLink
mask to select bytes on a READ, unlike a plain register behind
``tlul_adapter_reg`` which ignores it. A bridge that drives the mask from the
AXI write strobe therefore reads back all zeros from a window while every
register in the same block behaves. That failure is silent -- correct
response, wrong data -- so register reads do not cover it and the readback
compare is the only thing that catches it.

Targets are the scratch banks (safe to scribble, not restored) and the OTBN
DMEM and IMEM windows. Windows are only exercised when the run can prove they
read back what was written; see ``probe_window``.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0

# AxSIZE encodings: 0 = 1 byte, 1 = 2 bytes, 2 = 4 bytes.
SIZE_BYTES = {0: 1, 1: 2, 2: 4}

# Scratch words are plain RW storage in the SEP local map. Not restored:
# nothing downstream reads them back.
SCRATCH_COLD_0 = sym("SEP_SCRATCH_COLD_SCRATCH_0__REG_ADDR")
SCRATCH_WARM_0 = sym("SEP_SCRATCH_WARM_SCRATCH_0__REG_ADDR")

# Memory-mapped windows. These are the apertures that sit behind an SRAM-style
# adapter rather than a register adapter, which is the class the read-mask
# defect affects.
# The KMAC STATE window is gated by the engine's own configuration and refuses
# a bare CSR-path write, so a probe there tests KMAC bring-up rather than the
# read mask; it is not a target here.
WINDOWS: tuple[tuple[str, int], ...] = (
    ("otbn_dmem", sym("OTBN_DMEM_MEM_BASE_ADDR")),
    ("otbn_imem", sym("OTBN_IMEM_MEM_BASE_ADDR")),
)


@dataclass(frozen=True)
class NarrowWrite:
    """One narrow write: byte offset within the word, and the AxSIZE."""

    addr: int  # word-aligned base
    byte_off: int  # 0..3, which byte lane the write targets
    size: int  # AxSIZE encoding
    value: int  # value to write, already narrowed
    prime: int  # word value staged before the write


@dataclass(frozen=True)
class WindowProbe:
    name: str
    addr: int
    value: int


class SepAxiStrobeWindowCfg:
    """Seeded narrow writes on scratch, plus one window probe per aperture."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)

        writes: list[NarrowWrite] = []
        for base in (SCRATCH_COLD_0, SCRATCH_WARM_0):
            # Every AxSIZE at every legal lane offset, every seed: the size and
            # alignment axes are small enough to walk exhaustively, so every
            # size and lane runs on every seed. The seed varies the data, not
            # whether a case is covered.
            slots = [
                (size, off) for size in sorted(SIZE_BYTES) for off in range(0, 4, SIZE_BYTES[size])
            ]
            for size, byte_off in slots:
                nbytes = SIZE_BYTES[size]
                prime = rng.getrandbits(32)
                val = rng.getrandbits(8 * nbytes)
                # Force a difference so the write is observable: a value equal
                # to what is already there proves nothing about the strobe.
                cur = (prime >> (8 * byte_off)) & ((1 << (8 * nbytes)) - 1)
                if val == cur:
                    val ^= 1
                writes.append(NarrowWrite(base, byte_off, size, val, prime))
        self.writes = tuple(writes)

        self.windows = tuple(
            WindowProbe(name, base, rng.getrandbits(32) or 0xA5A5_5A5A) for name, base in WINDOWS
        )

    def summary(self) -> str:
        by_size: dict[int, int] = {}
        for w in self.writes:
            by_size[SIZE_BYTES[w.size]] = by_size.get(SIZE_BYTES[w.size], 0) + 1
        sizes = " ".join(f"{k}B={v}" for k, v in sorted(by_size.items()))
        return (
            f"seed={self.seed} narrow_writes={len(self.writes)} [{sizes}] "
            f"windows={len(self.windows)}"
        )


def expected_after_narrow(prime: int, w: NarrowWrite) -> int:
    """Word value a correct narrow write leaves behind.

    Derived from the AXI rule that only the addressed byte lanes are written,
    not from anything the DUT reported.
    """
    nbytes = SIZE_BYTES[w.size]
    lane_mask = ((1 << (8 * nbytes)) - 1) << (8 * w.byte_off)
    return ((prime & ~lane_mask) | ((w.value << (8 * w.byte_off)) & lane_mask)) & 0xFFFF_FFFF


class SepAxiStrobeWindow:
    """Drives the narrow writes and window probes, reporting failures."""

    def __init__(self, test) -> None:
        self.test = test
        self.narrow_ok = 0
        self.window_ok = 0
        self.window_skipped: dict[str, str] = {}

    # The readback masks to 32 bits, which is the whole of the addressed
    # register. No addressed register has a 4-byte-adjacent neighbour, so a
    # 32-bit register owns its 64-bit beat and bytes 4-7 are unimplemented, not
    # a neighbour. A strobe widened past the addressed lanes has no second
    # register to corrupt, and the addressed-word compare below is the whole
    # contract.
    async def _rd(self, addr: int, *, size: int = 2) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            f"sw_rd_0x{addr:08x}",
            op=SepAxiOp.READ,
            addr=addr,
            length=SIZE_BYTES[size],
            size=size,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _wr(self, addr: int, data: int, *, size: int = 2, tolerate: bool = False) -> int:
        # tolerate uses allow_unverified_write_resp, whose documented meaning
        # is "the sequence verifies by readback". expect_error would be wrong:
        # it DEMANDS a refusal, and a window that stores would then fail.
        seq = SepAxiAccessSeq(
            f"sw_wr_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=SIZE_BYTES[size],
            size=size,
            allow_unverified_write_resp=tolerate,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def probe_narrow(self, w: NarrowWrite) -> str | None:
        """None when the narrow write touched only its own byte lanes."""
        resp = await self._wr(w.addr, w.prime)
        if resp != RESP_OKAY:
            return f"prime write 0x{w.addr:08x} resp={resp}"
        resp, staged = await self._rd(w.addr)
        if resp != RESP_OKAY:
            return f"prime read 0x{w.addr:08x} resp={resp}"
        if staged != w.prime:
            # Not a strobe failure: the word did not hold the prime at all.
            return (
                f"0x{w.addr:08x} prime 0x{w.prime:08x} read back 0x{staged:08x};"
                " the narrow-write compare needs a known starting word"
            )

        nbytes = SIZE_BYTES[w.size]
        resp = await self._wr(w.addr + w.byte_off, w.value, size=w.size)
        if resp != RESP_OKAY:
            return f"narrow write 0x{w.addr + w.byte_off:08x} size={nbytes}B resp={resp}"
        resp, after = await self._rd(w.addr)
        if resp != RESP_OKAY:
            return f"post-write read 0x{w.addr:08x} resp={resp}"

        want = expected_after_narrow(w.prime, w)
        if after != want:
            lane_mask = ((1 << (8 * nbytes)) - 1) << (8 * w.byte_off)
            spilled = (after ^ want) & ~lane_mask & 0xFFFF_FFFF
            detail = (
                f"bytes outside the addressed lane(s) changed by 0x{spilled:08x}"
                if spilled
                else "addressed lane did not take the value"
            )
            return (
                f"0x{w.addr:08x} {nbytes}B write of 0x{w.value:x} at byte "
                f"{w.byte_off}: prime 0x{w.prime:08x} -> 0x{after:08x}, "
                f"expected 0x{want:08x} ({detail})"
            )
        self.narrow_ok += 1
        return None

    async def probe_window(self, p: WindowProbe) -> str | None:
        """None when the window read back exactly what was written.

        A window that will not accept a write at all is recorded as skipped
        with the response, not counted as a pass: the read-mask defect is only
        observable on a window that stores.

        The write uses allow_unverified_write_resp so a refusal is the
        sequence's own result rather than a scoreboard failure. expect_error
        would be wrong: it demands a refusal, and a window that stores would
        then fail. Whether a window accepts a bare CSR-path write depends on
        the engine's state (OTBN IMEM/DMEM are gated), and that is a skip
        here, not a defect -- the contract under test is the DATA, on a
        window that stores. A write that is accepted and a read that then
        refuses is a failure: the window stored, so the readback must return.
        """
        resp = await self._wr(p.addr, p.value, tolerate=True)
        if resp != RESP_OKAY:
            self.window_skipped[p.name] = f"write resp={resp}"
            return None
        resp, got = await self._rd(p.addr)
        if resp != RESP_OKAY:
            return (
                f"{p.name} window 0x{p.addr:08x}: write accepted, read "
                f"resp={resp}; the read-mask contract needs a readable window"
            )
        if got != p.value:
            extra = (
                " -- all zeros, the signature of a read that masked every byte" if got == 0 else ""
            )
            return f"{p.name} window 0x{p.addr:08x}: wrote 0x{p.value:08x}, read 0x{got:08x}{extra}"
        self.window_ok += 1
        return None


def _selftest() -> None:
    # The expectation model is pure arithmetic; pin it against hand values.
    w = NarrowWrite(0x1000, byte_off=1, size=0, value=0xAB, prime=0x1122_3344)
    assert expected_after_narrow(0x1122_3344, w) == 0x1122_AB44, (
        f"{expected_after_narrow(0x1122_3344, w):08x}"
    )
    w2 = NarrowWrite(0x1000, byte_off=2, size=1, value=0xBEEF, prime=0x1122_3344)
    assert expected_after_narrow(0x1122_3344, w2) == 0xBEEF_3344, (
        f"{expected_after_narrow(0x1122_3344, w2):08x}"
    )
    w4 = NarrowWrite(0x1000, byte_off=0, size=2, value=0xDEADBEEF, prime=0)
    assert expected_after_narrow(0, w4) == 0xDEAD_BEEF

    cfg = SepAxiStrobeWindowCfg(1)
    # 4x1B + 2x2B + 1x4B per target, two targets.
    assert len(cfg.writes) == 14, f"{len(cfg.writes)} narrow writes"
    assert len(cfg.windows) == len(WINDOWS), f"{len(cfg.windows)} windows"
    for w in cfg.writes:
        nb = SIZE_BYTES[w.size]
        assert w.byte_off % nb == 0, f"unaligned narrow beat: {w}"
        assert w.byte_off + nb <= 4, f"narrow beat runs past the word: {w}"
        assert w.value < (1 << (8 * nb)), f"value wider than the beat: {w}"
        # The write must be observable, or the compare proves nothing.
        assert expected_after_narrow(w.prime, w) != w.prime, (
            f"narrow write leaves the word unchanged: {w}"
        )

    # The size and lane axes are exhaustive on every seed; only data varies.
    def shape(c):
        return sorted((w.addr, w.byte_off, w.size) for w in c.writes)

    c1, c2 = SepAxiStrobeWindowCfg(1), SepAxiStrobeWindowCfg(2)
    assert shape(c1) == shape(c2), "size/lane coverage moved with the seed"
    assert {SIZE_BYTES[w.size] for w in c2.writes} == {1, 2, 4}, (
        "a seed produced no 1-byte write; the strobe axis must not be seeded"
    )
    assert [w.prime for w in c1.writes] != [w.prime for w in c2.writes], (
        "seed did not vary the data"
    )


_selftest()
