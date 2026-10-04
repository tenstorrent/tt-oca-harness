# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SRAM INCR bursts from the SMN-inbound master: config, byte model, port taps.

``hw/sys/sep/doc/fabric.adoc``: the SRAM target "serves INCR bursts of every
length", and of the crossbar initiators only the System Interface (the
external inbound master) may issue bursts. ``memory_map.adoc`` lists SRAM
among the regions that accept bursts. AXI4 (IHI 0022, A3.4.3) gives the
write-strobe rule the byte model applies: a byte whose strobe is low is not
written.

The inbound filter decides on the address, ``prot[1]``, ``user[3:0]`` and
``AxLEN`` only (``hw/ip/axi_filter/doc/index.adoc``). The window here is two
entries over the same SRAM span, one per ``allow_ns`` value, both with
``src_id = 0`` and ``allow_burst = 1``, so every drawn access is admitted.
``allow_burst = 1`` makes the filter granule 4 KB; the span is whole pages.

``SepSramInboundCfg`` is the single source of truth for the window, every
burst's start, length and data, the strobe overlay and the CPU-LSU words.
``SepSramByteModel`` is the golden image.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import sym

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
BEAT_BYTES = 8
WORD_BITS = 64
MASK64 = (1 << WORD_BITS) - 1
# AXI4 A3.4.1: a burst must not cross a 4 KB boundary, and INCR allows up to
# 256 beats.
PAGE_BYTES = 0x1000
MAX_BEATS = 256
WINDOW_PAGES = 4
# The overlay write is short enough to stay a few beats with partial first and
# last strobes.
OVERLAY_MAX_BYTES = 64
# AXI4 A7.2.4: an exclusive burst is at most 16 beats and 128 bytes, so with
# 8-byte beats at most 2**4 beats.
EXCL_MAX_LOG2_BEATS = 4
# CPU-LSU words written into each burst's span before it is read back.
LSU_POKES = 2
# CPU-LSU spot reads of each burst's span besides the first and last beat.
LSU_SPOT_READS = 2
N_CASES = 12
# AXI4 AxSIZE for an 8-byte beat.
SIZE_8B = 3

_AX_FIELDS = (
    "id",
    "addr",
    "len",
    "size",
    "burst",
    "lock",
    "cache",
    "prot",
    "qos",
    "region",
    "user",
)


def _walk_one(bit: int) -> int:
    return 1 << bit


def _walk_zero(bit: int) -> int:
    return MASK64 ^ (1 << bit)


class SepSramInboundCase:
    """One burst: span, data, strobe overlay and the CPU-LSU pokes/spots."""

    def __init__(self, idx: int, start: int, beats: int, kind: str, words: list[int]) -> None:
        self.idx = idx
        self.start = start
        self.beats = beats
        self.kind = kind
        self.words = words
        self.ov_addr = start
        self.ov_data = b""
        self.pokes: list[tuple[int, int]] = []
        self.spots: list[int] = []
        # ARLOCK of the read: None draws it when the read is exclusive-legal.
        self.read_lock: int | None = None

    @property
    def nbytes(self) -> int:
        return self.beats * BEAT_BYTES

    @property
    def end(self) -> int:
        return self.start + self.nbytes

    def payload(self) -> int:
        v = 0
        for i, w in enumerate(self.words):
            v |= w << (WORD_BITS * i)
        return v

    def ov_beats(self) -> list[int]:
        """Beat addresses the overlay touches."""
        first = self.ov_addr & ~(BEAT_BYTES - 1)
        last = (self.ov_addr + len(self.ov_data) - 1) & ~(BEAT_BYTES - 1)
        return list(range(first, last + BEAT_BYTES, BEAT_BYTES))

    def summary(self) -> str:
        return (
            f"case {self.idx}: 0x{self.start:08x} {self.beats} beats ({self.kind}), "
            f"overlay 0x{self.ov_addr:08x}+{len(self.ov_data)} B over "
            f"{len(self.ov_beats())} beats, LSU pokes "
            f"{[hex(a) for a, _ in self.pokes]}"
        )


class SepSramInboundCfg:
    """Seeded window and burst cases. Lengths 1 and 256 run on every seed, so
    AxLEN takes both of its extreme values, and so do two short bursts whose
    shape meets the AXI4 exclusive-access rules, one of them read with ARLOCK
    set; the rest are drawn."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.rng = rng
        n_pages = SRAM_SIZE // PAGE_BYTES
        self.win_base = SRAM_BASE + rng.randrange(0, n_pages - WINDOW_PAGES + 1) * PAGE_BYTES
        self.win_end = self.win_base + WINDOW_PAGES * PAGE_BYTES - 1
        short = [1 << rng.randrange(1, EXCL_MAX_LOG2_BEATS + 1) for _ in range(2)]
        shapes = [
            (MAX_BEATS, False, None),
            (1, False, None),
            (short[0], True, 1),
            (short[1], True, None),
        ]
        shapes += [(rng.randrange(2, MAX_BEATS + 1), False, None) for _ in range(N_CASES - 4)]
        for i in range(len(shapes) - 1, 0, -1):
            j = rng.randrange(0, i + 1)
            shapes[i], shapes[j] = shapes[j], shapes[i]
        kinds = ("walk1", "walk0", "random")
        k0 = rng.randrange(len(kinds))
        self.cases: list[SepSramInboundCase] = []
        for idx, (beats, aligned, read_lock) in enumerate(shapes):
            page = self.win_base + rng.randrange(WINDOW_PAGES) * PAGE_BYTES
            step = beats if aligned else 1
            off = rng.randrange(0, (PAGE_BYTES // BEAT_BYTES - beats) // step + 1) * step
            start = page + off * BEAT_BYTES
            kind = kinds[(k0 + idx) % len(kinds)]
            rot = rng.randrange(WORD_BITS)
            if kind == "walk1":
                words = [_walk_one((rot + i) % WORD_BITS) for i in range(beats)]
            elif kind == "walk0":
                words = [_walk_zero((rot + i) % WORD_BITS) for i in range(beats)]
            else:
                words = [rng.getrandbits(WORD_BITS) for _ in range(beats)]
            c = SepSramInboundCase(idx, start, beats, kind, words)
            c.read_lock = read_lock
            ov_off = rng.randrange(0, c.nbytes)
            ov_len = rng.randrange(1, min(OVERLAY_MAX_BYTES, c.nbytes - ov_off) + 1)
            c.ov_addr = start + ov_off
            c.ov_data = bytes(rng.getrandbits(8) for _ in range(ov_len))
            beat_addrs = [start + i * BEAT_BYTES for i in range(beats)]
            # Pokes avoid the overlay's beats, so the strobe check always
            # grades the overlay against the burst data it merged into.
            free = [b for b in beat_addrs if b not in c.ov_beats()]
            for _ in range(min(LSU_POKES, len(free))):
                addr = rng.choice(free)
                free.remove(addr)
                c.pokes.append((addr, rng.getrandbits(WORD_BITS)))
            spots = {beat_addrs[0], beat_addrs[-1]}
            for _ in range(LSU_SPOT_READS):
                spots.add(rng.choice(beat_addrs))
            c.spots = sorted(spots)
            self.cases.append(c)

    def summary(self) -> str:
        return (
            f"seed={self.seed} window=0x{self.win_base:08x}..0x{self.win_end:08x} "
            f"cases={len(self.cases)} lengths={[c.beats for c in self.cases]}"
        )


class SepSramByteModel:
    """Golden SRAM image of the bytes this test wrote. A byte the test has not
    written has no expected value, and a read of it fails the model."""

    def __init__(self) -> None:
        self.mem: dict[int, int] = {}

    def write(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def write_word(self, addr: int, word: int) -> None:
        self.write(addr, word.to_bytes(BEAT_BYTES, "little"))

    def word(self, addr: int) -> int:
        try:
            return int.from_bytes(bytes(self.mem[addr + i] for i in range(BEAT_BYTES)), "little")
        except KeyError as exc:
            raise AssertionError(f"model has no value for 0x{addr:08x}") from exc

    def span(self, addr: int, nbytes: int) -> int:
        return int.from_bytes(bytes(self.mem[addr + i] for i in range(nbytes)), "little")


async def capture_ax(channel: str, prefix: str = "m_axi") -> dict[str, int]:
    """Every request field of the next AW or AR handshake on a TB port.

    Start with ``cocotb.start_soon`` before the access and read the result
    after it. The fields are what the master presented at the handshake, so a
    compare against the drawn values proves the stimulus reached the port."""
    dut = cocotb.top
    sig = {f: getattr(dut, f"{prefix}_{channel}{f}") for f in _AX_FIELDS}
    valid = getattr(dut, f"{prefix}_{channel}valid")
    ready = getattr(dut, f"{prefix}_{channel}ready")
    while True:
        await RisingEdge(dut.clk_i)
        if valid.value == 1 and ready.value == 1:
            return {f: int(s.value) for f, s in sig.items()}


async def capture_rlast(rid: int, prefix: str = "m_axi") -> list[int]:
    """RLAST of every R handshake that carries ``rid`` on a TB port, up to and
    including the first one with RLAST set.

    Start with ``cocotb.start_soon`` before the read and read the result after
    it. The flags are what the DUT presented on the R channel, so the test
    grades where RLAST fell instead of relying on the master VIP."""
    dut = cocotb.top
    valid = getattr(dut, f"{prefix}_rvalid")
    ready = getattr(dut, f"{prefix}_rready")
    rid_sig = getattr(dut, f"{prefix}_rid")
    last = getattr(dut, f"{prefix}_rlast")
    flags: list[int] = []
    while True:
        await RisingEdge(dut.clk_i)
        if valid.value == 1 and ready.value == 1 and int(rid_sig.value) == rid:
            flags.append(int(last.value))
            if flags[-1]:
                return flags
