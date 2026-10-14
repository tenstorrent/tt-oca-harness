# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction address and image model of a secure DMA memory-to-memory transfer.

Pure model: it reads no DUT signal. It states, for a transfer of ``total``
bytes in chunks of ``chunk`` bytes at a transfer width of ``w`` bytes, the
address of each transaction, the destination image the transfer leaves, and
the write-strobe byte lanes of each write beat on the 64-bit DMA master.

``DmaZeroFill`` models a zero fill (CONTROL.OPCODE 4, ``dma.hjson``): no read,
and each write beat clears the bytes it covers. Its final beat can be narrower
than the width; the enabled memory range stops the fill at the first beat that
leaves it, before that beat is written.

Transaction k runs from 0 to total/w - 1. Its chunk is j = floor(k*w/C) and
its position in the chunk is p = k - j*C/w. The address of transaction k at a
side with base address ``base`` is:

* INCREMENT=1, WRAP=1: base + p*w (each chunk starts again at base),
* INCREMENT=1, WRAP=0: base + k*w,
* INCREMENT=0: base.

TRANSFER_WIDTH encodings 0, 1 and 2 select 1, 2 and 4 bytes per transaction
(``dma.hjson``, TRANSFER_WIDTH). Transaction k reads w bytes at its source
address and writes them at its destination address, so a later transaction
that hits the same destination address overwrites an earlier one. The model
assumes that the source and the destination footprints are disjoint.

The sentinel draw returns one byte value that no source byte takes, so every
byte that the transfer writes differs from a sentinel-filled destination.

Self-test: ``python3 cocotb/env/sep_dma_model.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

WIDTH_BYTES = {0: 1, 1: 2, 2: 4}
BUS_BYTES = 8


def width_bytes(enc: int) -> int:
    """Bytes per transaction of a TRANSFER_WIDTH encoding (0, 1 or 2)."""
    try:
        return WIDTH_BYTES[enc]
    except KeyError as exc:
        raise ValueError(f"TRANSFER_WIDTH encoding {enc} has no stated width") from exc


def txn_addr(base: int, k: int, w: int, chunk: int, inc: bool, wrap: bool) -> int:
    """Address of transaction ``k`` at one side of the transfer."""
    if not inc:
        return base
    if wrap:
        j = (k * w) // chunk
        p = k - j * (chunk // w)
        return base + p * w
    return base + k * w


def wstrb_lanes(addr: int, w: int, bus_bytes: int = BUS_BYTES) -> int:
    """WSTRB byte lanes of a ``w``-byte write at ``addr`` on a ``bus_bytes`` bus."""
    lane = addr % bus_bytes
    if lane + w > bus_bytes:
        raise ValueError(f"a {w}-byte write at 0x{addr:x} crosses a {bus_bytes}-byte beat")
    return ((1 << w) - 1) << lane


@dataclass(frozen=True)
class DmaXfer:
    """One memory-to-memory transfer as software programs it."""

    src_base: int
    dst_base: int
    total: int
    chunk: int
    width_enc: int = 2
    src_inc: bool = True
    src_wrap: bool = False
    dst_inc: bool = True
    dst_wrap: bool = False

    def __post_init__(self) -> None:
        w = width_bytes(self.width_enc)
        if self.total <= 0 or self.chunk <= 0:
            raise ValueError("total and chunk are positive")
        if self.total % w or self.chunk % w:
            raise ValueError(f"total {self.total} and chunk {self.chunk} are multiples of {w}")
        for name, addr in (("src", self.src_base), ("dst", self.dst_base)):
            if addr % w:
                raise ValueError(f"{name} base 0x{addr:x} is not aligned to {w}")

    @property
    def w(self) -> int:
        return width_bytes(self.width_enc)

    @property
    def n_txn(self) -> int:
        return self.total // self.w

    @property
    def n_chunks(self) -> int:
        return -(-self.total // self.chunk)

    def chunk_of(self, k: int) -> int:
        return (k * self.w) // self.chunk

    def src_addr(self, k: int) -> int:
        return txn_addr(self.src_base, k, self.w, self.chunk, self.src_inc, self.src_wrap)

    def dst_addr(self, k: int) -> int:
        return txn_addr(self.dst_base, k, self.w, self.chunk, self.dst_inc, self.dst_wrap)

    def ar_addrs(self) -> list[int]:
        """Expected source (AR) address of every transaction, in order."""
        return [self.src_addr(k) for k in range(self.n_txn)]

    def aw_addrs(self) -> list[int]:
        """Expected destination (AW) address of every transaction, in order."""
        return [self.dst_addr(k) for k in range(self.n_txn)]

    def wstrbs(self) -> list[int]:
        """Expected WSTRB byte lanes of every write beat, in order."""
        return [wstrb_lanes(a, self.w) for a in self.aw_addrs()]

    def src_footprint(self) -> range:
        addrs = self.ar_addrs()
        return range(min(addrs), max(addrs) + self.w)

    def dst_footprint(self) -> range:
        addrs = self.aw_addrs()
        return range(min(addrs), max(addrs) + self.w)

    def dst_image(self, src: Mapping[int, int], dst_init: Mapping[int, int]) -> dict[int, int]:
        """Destination bytes after the transfer: ``dst_init`` with every write applied.

        ``src`` maps each source byte address to its value and ``dst_init``
        maps each destination byte address (guard bytes included) to its value
        before the transfer. A missing source byte is a model input error.
        """
        img = dict(dst_init)
        for k in range(self.n_txn):
            s = self.src_addr(k)
            d = self.dst_addr(k)
            for b in range(self.w):
                if s + b not in src:
                    raise KeyError(f"source byte 0x{s + b:x} of transaction {k} is not given")
                img[d + b] = src[s + b]
        return img


@dataclass(frozen=True)
class ZeroBeat:
    """One write beat of a zero fill: its first byte address and its byte count."""

    addr: int
    nbytes: int

    @property
    def wstrb(self) -> int:
        """WSTRB byte lanes on the 64-bit DMA master."""
        return wstrb_lanes(self.addr, self.nbytes)


@dataclass(frozen=True)
class DmaZeroFill:
    """One zero fill (OPCODE 4) as software programs it.

    A transfer of more than one chunk has a ``chunk`` that is a multiple of
    the width, so only the last beat of the transfer can be narrower than the
    width. A destination that does not increment is limited to one chunk: at a
    chunk end with INCREMENT=0 and WRAP=0 the engine advances DST_ADDR by
    CHUNK_DATA_SIZE.
    """

    dst_base: int
    total: int
    chunk: int
    width_enc: int = 2
    dst_inc: bool = True
    dst_wrap: bool = False

    def __post_init__(self) -> None:
        w = width_bytes(self.width_enc)
        if self.total <= 0 or self.chunk <= 0:
            raise ValueError("total and chunk are positive")
        if self.chunk % w and self.chunk < self.total:
            raise ValueError(f"chunk {self.chunk} of a multi-chunk transfer is a multiple of {w}")
        if self.dst_base % w:
            raise ValueError(f"dst base 0x{self.dst_base:x} is not aligned to {w}")
        if not self.dst_inc and self.chunk < self.total:
            raise ValueError("a fixed destination is limited to one chunk")

    @property
    def w(self) -> int:
        return width_bytes(self.width_enc)

    @property
    def n_chunks(self) -> int:
        return -(-self.total // self.chunk)

    def beats(self) -> list[ZeroBeat]:
        """Every write beat, in order: the address and the bytes it clears."""
        out = []
        for k in range(-(-self.total // self.w)):
            addr = txn_addr(self.dst_base, k, self.w, self.chunk, self.dst_inc, self.dst_wrap)
            out.append(ZeroBeat(addr, min(self.w, self.total - k * self.w)))
        return out

    def beats_in_range(self, base: int, limit: int) -> list[ZeroBeat]:
        """The beats written under an enabled memory range [base, limit].

        The engine checks each beat before it writes it and stops at the first
        beat whose bytes leave the range.
        """
        out = []
        for beat in self.beats():
            if beat.addr < base or beat.addr + beat.nbytes - 1 > limit:
                break
            out.append(beat)
        return out

    def dst_image(self, dst_init: Mapping[int, int], beats: Iterable[ZeroBeat]) -> dict[int, int]:
        """``dst_init`` with every byte of ``beats`` cleared."""
        img = dict(dst_init)
        for beat in beats:
            for b in range(beat.nbytes):
                img[beat.addr + b] = 0
        return img


def words_to_bytes(base: int, words: Iterable[int]) -> dict[int, int]:
    """Little-endian byte map of 32-bit ``words`` stored from ``base``."""
    out: dict[int, int] = {}
    for i, word in enumerate(words):
        for b in range(4):
            out[base + 4 * i + b] = (word >> (8 * b)) & 0xFF
    return out


def bytes_to_words(img: Mapping[int, int], base: int, n_words: int) -> list[int]:
    """The ``n_words`` little-endian 32-bit words of ``img`` from ``base``."""
    return [sum(img[base + 4 * i + b] << (8 * b) for b in range(4)) for i in range(n_words)]


def draw_sentinel_byte(rng, src_bytes: Iterable[int]) -> int:
    """A byte value, drawn from ``rng``, that no byte of ``src_bytes`` takes."""
    used = set(src_bytes)
    free = [v for v in range(256) if v not in used]
    if not free:
        raise ValueError("every byte value appears in the source; no sentinel exists")
    return int(free[rng.randrange(len(free))])


def draw_source_words(rng, n: int, sentinel: int) -> list[int]:
    """``n`` unique 32-bit words, drawn from ``rng``, with no byte equal to ``sentinel``."""
    seen: set[int] = set()
    out: list[int] = []
    while len(out) < n:
        word = 0
        for b in range(4):
            v = rng.randrange(255)
            word |= (v if v < sentinel else v + 1) << (8 * b)
        if word not in seen:
            seen.add(word)
            out.append(word)
    return out


def _selftest() -> int:
    # Hand vectors: width 4, chunk 8, total 16 => 4 txns, 2 chunks.
    x = DmaXfer(0x1000_0000, 0x1000_1000, total=16, chunk=8, src_wrap=True)
    assert x.n_txn == 4 and x.n_chunks == 2
    assert x.ar_addrs() == [0x1000_0000, 0x1000_0004, 0x1000_0000, 0x1000_0004]
    assert x.aw_addrs() == [0x1000_1000, 0x1000_1004, 0x1000_1008, 0x1000_100C]
    assert x.wstrbs() == [0x0F, 0xF0, 0x0F, 0xF0]
    # Width 1, no increment at the destination.
    y = DmaXfer(0x2000, 0x3001, total=4, chunk=4, width_enc=0, dst_inc=False)
    assert y.aw_addrs() == [0x3001] * 4
    assert y.wstrbs() == [0x02] * 4
    src = words_to_bytes(0x2000, [0x44332211])
    img = y.dst_image(src, {0x3000 + i: 0xEE for i in range(4)})
    assert [img[0x3000 + i] for i in range(4)] == [0xEE, 0x44, 0xEE, 0xEE]
    # Width 2 with wrap at both sides and chunk 4.
    z = DmaXfer(0x10, 0x20, total=8, chunk=4, width_enc=1, src_wrap=True, dst_wrap=True)
    assert z.ar_addrs() == [0x10, 0x12, 0x10, 0x12]
    assert z.wstrbs() == [0x03, 0x0C, 0x03, 0x0C]
    # Wrap with one chunk equals no wrap.
    a = DmaXfer(0x0, 0x100, total=32, chunk=32, src_wrap=True)
    b = DmaXfer(0x0, 0x100, total=32, chunk=32)
    assert a.ar_addrs() == b.ar_addrs()
    # Word and byte maps round-trip.
    words = [0x0102_0304, 0xA0B0_C0D0]
    assert bytes_to_words(words_to_bytes(0x40, words), 0x40, 2) == words
    # Sentinel and drawn words exclude each other; words are unique.
    from sep_seeded_rng import SepSeededRng

    rng = SepSeededRng(7)
    s = draw_sentinel_byte(rng, range(255))
    assert s == 255
    ws = draw_source_words(rng, 64, 0x5A)
    assert len(set(ws)) == 64
    assert all(((w >> (8 * i)) & 0xFF) != 0x5A for w in ws for i in range(4))
    # Zero fill, width 4, total 10 in one chunk: two full beats and a 2-byte beat.
    z4 = DmaZeroFill(0x1000_0004, total=10, chunk=12)
    assert [(b.addr, b.nbytes) for b in z4.beats()] == [
        (0x1000_0004, 4),
        (0x1000_0008, 4),
        (0x1000_000C, 2),
    ]
    assert [b.wstrb for b in z4.beats()] == [0xF0, 0x0F, 0x30]
    # One chunk of a total that is not a multiple of the width.
    z1 = DmaZeroFill(0x100, total=6, chunk=6)
    assert [(b.addr, b.nbytes) for b in z1.beats()] == [(0x100, 4), (0x104, 2)]
    # Width 2 wrapping at the destination: chunk 4 replays the first two halves.
    zw = DmaZeroFill(0x2000, total=8, chunk=4, width_enc=1, dst_wrap=True)
    assert [b.addr for b in zw.beats()] == [0x2000, 0x2002, 0x2000, 0x2002]
    # The range stops the fill at the first beat that leaves it.
    assert z4.beats_in_range(0x1000_0004, 0x1000_000B) == z4.beats()[:2]
    assert z4.beats_in_range(0x1000_0004, 0x1000_000D) == z4.beats()
    assert z4.beats_in_range(0x1000_0008, 0x1000_FFFF) == []
    img = z4.dst_image({0x1000_0003 + i: 0xA5 for i in range(14)}, z4.beats())
    assert [img[0x1000_0003 + i] for i in range(14)] == [0xA5] + [0] * 10 + [0xA5] * 3
    for bad in (
        lambda: DmaXfer(0x2, 0x0, total=8, chunk=8),
        lambda: DmaXfer(0x0, 0x0, total=6, chunk=8),
        lambda: width_bytes(3),
        lambda: DmaZeroFill(0x0, total=8, chunk=6),
        lambda: DmaZeroFill(0x0, total=12, chunk=10),
        lambda: DmaZeroFill(0x0, total=16, chunk=8, dst_inc=False),
    ):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("an illegal transfer was accepted")
    print("sep_dma_model self-test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
