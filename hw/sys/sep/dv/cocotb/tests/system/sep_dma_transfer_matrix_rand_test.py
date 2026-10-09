# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA transfer matrix: address modes, widths, geometry, range edges, inline hash.

RANDOMIZED (SepSeededRng from the run seed). The leaf programs the secure DMA
over the CPU-LSU splice (no CPU) and runs four legs on SEP SRAM
(``memory_map.adoc``, 0x1000_0000 to 0x1003_FFFF):

* Leg A: the 16 source {INCREMENT, WRAP} x destination {INCREMENT, WRAP}
  cells, each at a drawn width encoding (every encoding on every seed), a
  drawn chunk size and a drawn chunk count. The expected destination image
  and beat addresses come from ``env/sep_dma_model.DmaXfer``, a model of the
  register text (``secure_dma.adoc``, SRC_CONFIG, DST_CONFIG,
  TRANSFER_WIDTH). The cells that ``sep_dma_basic_test`` grades run only with
  two or more chunks (three or more for the source-wrap pair).
* Leg B: single-chunk totals 4 bytes and a drawn 64 to 4096 bytes, 16384 bytes
  as four 4096-byte chunks and two drawn multi-chunk transfers, back to back
  with no software clear of STATUS.DONE between them.
* Leg C: ENABLED_MEMORY_RANGE_BASE and LIMIT exactly on the region edges (low,
  high, both, and both with a guard outside the range at the low end, the
  high end and both ends), each in a drawn region order, with a wide-range
  control run of the same copy.
* Leg D: SHA-256, SHA-384 and SHA-512 inline hashing on the published 56-byte
  and 112-byte vectors at both DIGEST_SWAP values, two drawn lengths per
  algorithm, an equal split of each message into 2 to 4 chunks of one
  transfer, and one long message. The digest golden comes from Python
  ``hashlib``; the leaf never takes an expected value from the DUT.

DIGEST_SWAP (``secure_dma.adoc``, CONTROL.DIGEST_SWAP): with DIGEST_SWAP=1 each
digest register holds its four digest bytes in big-endian byte order, so the
little-endian bytes of word i are digest bytes 4i to 4i+3 and SHA2_DIGEST_0
holds the first four bytes. With DIGEST_SWAP=0 each word is the byte reversal
of that value at the same position.

Probes: register and SRAM frontdoor over ``s_axi``; ``dma_busy_probe_o``;
bit 9 of ``sep_internal_interrupts_probe_o`` (PIC source 10, DMA chunk done);
the observation taps ``dma_axi_req_probe_o`` (DMA master AR/AW/W/B after the
alias remap) and ``dma_status_probe_o`` (STATUS levels), read through
``env/sep_dma_tap.py``. No inject.

Checkers (log shape ``CHK-<ID> PASS|FAIL seed=<n> ...``):
  CHK-DMA-IMAGE       per Leg A cell: destination and guard words equal the
                      model image; STATUS.ERROR and ERROR_CODE read 0.
  CHK-DMA-BEAT        per Leg A cell: AxLEN 0 on every AR and AW, AR and AW
                      and W counts equal TOTAL/width, WSTRB popcount equals the
                      width, read address step 4 inside a chunk at width 4.
  CHK-DMA-ADDR        per Leg A cell: every AR/AW address equals the model
                      (AxADDR[31:2] and the WSTRB lanes at widths 1 and 2;
                      AxADDR[1:0] there only in ``OBS-DMA-ADDR-LOW``).
  CHK-DMA-GEOM        per Leg B transfer: DONE=1, BUSY=0, GO=0, ERROR=0,
                      destination equals source, guards intact. Control: a
                      CONTROL read with GO=1 while ``dma_busy_probe_o`` is 1.
  CHK-DMA-DONE-CLR    Leg B totals of 1024 bytes or more after the first: a
                      STATUS read with BUSY=1 shows DONE=0. Control: DONE=1 on
                      the read just before GO.
  CHK-DMA-CHUNKDONE   Leg B single-chunk transfers read CHUNK_DONE=0 on every
                      poll. Control: the multi-chunk transfers show
                      CHUNK_DONE=1 on a poll or a rise of PIC source 10.
  CHK-DMA-CHUNKRISE   per Leg A and Leg B transfer: n-1 to n CHUNK_DONE rises
                      (none for one chunk), each of the first n-1 followed by a
                      hardware fall, no STATUS write in the window.
  CHK-DMA-DONE-ORDER  per Leg A and Leg B transfer: B count equals AW count,
                      and no DONE rise comes before the last B handshake.
  CHK-DMA-RANGE-OK    per Leg C cell: the copy completes with ERROR=0 and the
                      data copied. Control: the same copy with the wide range.
  CHK-DMA-HASH        per graded Leg D run: digest words equal the hashlib
                      golden for the swap value; the copy equals the source.
  CHK-DMA-HASH-VALID  per Leg D run: SHA2_DIGEST_VALID reads 1 after the chain;
                      on the long message a BUSY=1 read shows it 0. Control:
                      it reads 1 just before the GO of the second run.
  CHK-DMA-HASH-CHAIN  per message with a split form: single-chunk and split
                      digests are equal.

The Leg D cells that ``sep_dma_hash_test`` grades (SHA-256 at 56 bytes as one
chunk at either swap value, SHA-256 at 56 bytes as two 28-byte chunks with
DIGEST_SWAP=1, SHA-384 at 56 bytes as one chunk with DIGEST_SWAP=1) are
controls: they log ``OBS-DMA-HASH-CTRL`` and print no CHK-DMA-HASH or
CHK-DMA-HASH-CHAIN line.

Run mode: no_cpu, target ``lsu_stub_all_live``, ``+skip_fuse_sense``, never
asserts ``rst_ni``; Verilator and VCS. Graded-window owner code from
``tb/sep_fcov_owner_codes.svh``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import cocotb
import pyuvm
from env.sep_bit_watch import SepBitWatch
from env.sep_dma_model import (
    DmaXfer,
    bytes_to_words,
    draw_sentinel_byte,
    draw_source_words,
    words_to_bytes,
)
from env.sep_dma_tap import DmaTapEvents, SepDmaTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_dma_ops import (
    CONTROL,
    DST_ADDR_HI,
    ERROR_CODE,
    ERROR_CODE_MASK,
    INTR_CHUNK_DONE,
    INTR_ENABLE,
    OP_COPY,
    OP_SHA256,
    OP_SHA384,
    OP_SHA512,
    SRC_ADDR_HI,
    ST_BUSY,
    ST_CHUNK_DONE,
    ST_DONE,
    ST_ERROR,
    STATUS,
    DmaStatus,
    DmaTimeout,
    SepDmaOps,
    SepMemWords,
    asid_word,
    control_word,
)

TEST = "sep_dma_transfer_matrix_rand_test"

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LIMIT = SRAM_BASE + SRAM_SIZE - 1
# ADDR_SPACE_ID = 0x77: source and destination ASID 7.
ASID = 0x7
GO_MASK = control_word(go=1)
# Clocks a re-GO waits for the rise of dma_busy_probe_o.
BUSY_RISE_BOUND = 2_000
# STATUS reads a wait for SHA2_DIGEST_VALID may take after DONE.
VALID_POLL_BOUND = 200
# CONTROL reads per Leg B transfer that look for GO=1 at BUSY=1.
CTRL_READ_TRIES = 8
# A total of this size or more lets a frontdoor read land while the engine runs.
LONG_TOTAL = 1024

# The order in which step 4 writes the transfer registers is drawn from these.
XFER_ORDER_REGS = (
    "SRC_ADDR_LO",
    "DST_ADDR_LO",
    "TOTAL_DATA_SIZE",
    "CHUNK_DATA_SIZE",
    "TRANSFER_WIDTH",
    "SRC_CONFIG",
    "DST_CONFIG",
)

# The 16 Leg A cells: (src INCREMENT, src WRAP, dst INCREMENT, dst WRAP).
CELLS = tuple((si, sw, di, dw) for si in (0, 1) for sw in (0, 1) for di in (0, 1) for dw in (0, 1))
# (cell, width encoding) pairs that sep_dma_basic_test grades at one chunk (or
# two for the source-wrap pair) -> the smallest chunk count this leaf uses.
BASIC_PAIRS_MIN_N = {
    ((1, 0, 1, 0), 0): 2,
    ((1, 0, 1, 0), 1): 2,
    ((1, 0, 1, 0), 2): 2,
    ((0, 1, 1, 0), 2): 2,
    ((1, 0, 0, 1), 2): 2,
    ((1, 1, 1, 0), 2): 3,
}

# Published SHA-2 vectors (FIPS 180-4 examples): 56 bytes for SHA-256 and
# 112 bytes for SHA-384 and SHA-512.
VEC56 = b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
VEC112 = (
    b"abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmn"
    b"hijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu"
)
BOUNDARY_LENGTHS = (52, 56, 60, 64, 108, 112, 116, 124, 128, 132)
ALGS = {
    256: (OP_SHA256, hashlib.sha256, 8),
    384: (OP_SHA384, hashlib.sha384, 12),
    512: (OP_SHA512, hashlib.sha512, 16),
}


def golden_words(alg: int, msg: bytes, swap: int) -> list[int]:
    """Expected SHA2_DIGEST_0 words of ``msg`` for one DIGEST_SWAP value (hashlib)."""
    digest = ALGS[alg][1](msg).digest()
    order = "little" if swap else "big"
    return [int.from_bytes(digest[4 * i : 4 * i + 4], order) for i in range(len(digest) // 4)]


def split_ks(length: int) -> list[int]:
    """Chunk counts k in {2, 3, 4} that split ``length`` bytes into equal 4-byte multiples."""
    return [k for k in (2, 3, 4) if length % k == 0 and (length // k) % 4 == 0]


def place(rng: SepSeededRng, sizes: list[int]) -> list[int]:
    """Disjoint 4-aligned SRAM addresses for blocks of ``sizes`` bytes, in a drawn order."""
    free = SRAM_SIZE - sum(sizes)
    if free < 0:
        raise ValueError(f"blocks of {sum(sizes)} bytes do not fit the SRAM")
    cuts = sorted(rng.randrange(free // 4 + 1) for _ in sizes)
    order = list(range(len(sizes)))
    rng.shuffle(order)
    out = [0] * len(sizes)
    pos = prev = 0
    for cut, i in zip(cuts, order):
        pos += (cut - prev) * 4
        prev = cut
        out[i] = SRAM_BASE + pos
        pos += sizes[i]
    return out


def ff(prefix: str, fc) -> str:
    """``<prefix>_value= <prefix>_expect= <prefix>_mask= <prefix>_rsvd=`` of a field compare."""
    m = fc.mask
    return (
        f"{prefix}_value=0x{fc.got & m:x} {prefix}_expect=0x{fc.expect & m:x} "
        f"{prefix}_mask=0x{m:x} {prefix}_rsvd=0x{fc.rsvd:x}"
    )


def poll_size(n_bytes: int) -> int:
    """Size handed to the poll bound of ``SepDmaOps``: twice the bytes moved.

    A frontdoor STATUS read takes about 14 core clocks and a 4-byte DMA
    transaction about 26, so ``SepDmaOps.done_bound`` of the plain size can
    expire on a long transfer that still runs. The bound stays linear in the
    size of the transfer.
    """
    return 2 * n_bytes


def sentinel_word(s: int) -> int:
    return s * 0x0101_0101


def cell_name(cell: tuple[int, int, int, int]) -> str:
    si, sw, di, dw = cell
    return f"{si}{sw}{di}{dw}"


def rle(items: list[str]) -> str:
    """Run-length form of a sequence of short tokens: ``tok*count,...``."""
    out: list[str] = []
    for tok in items:
        if out and out[-1].rsplit("*", 1)[0] == tok:
            head, cnt = out[-1].rsplit("*", 1)
            out[-1] = f"{head}*{int(cnt) + 1}"
        else:
            out.append(f"{tok}*1")
    return ",".join(out)


# ---------------------------------------------------------------- draws ----


@dataclass
class CopyXfer:
    """One memory-to-memory copy with its images (all drawn from the seed)."""

    x: DmaXfer
    sentinel: int
    src_words: list[int]
    src_addr: int  # first source word
    dst_region: int  # first destination word (guard words included)
    dst_region_words: int
    guard_words: list[int] = field(default_factory=list)  # addresses of guard words
    order: tuple[str, ...] = XFER_ORDER_REGS

    def expected_dst(self) -> list[int]:
        s = self.sentinel
        init = {self.dst_region + b: s for b in range(4 * self.dst_region_words)}
        img = self.x.dst_image(words_to_bytes(self.src_addr, self.src_words), init)
        return bytes_to_words(img, self.dst_region, self.dst_region_words)


@dataclass
class CellDraw:
    cell: tuple[int, int, int, int]
    enc: int
    n: int
    chunk: int
    copy: CopyXfer


@dataclass
class EdgeDraw:
    edge: str  # low, high, both, guard_low, guard_high, guard_both
    order: str  # src_low or dst_low
    size: int
    g_low: int
    g_high: int
    block: int
    sentinel: int
    src_words: list[int]

    @property
    def lo_region(self) -> int:
        return self.block + self.g_low

    @property
    def hi_region(self) -> int:
        # One in-range sentinel word sits between the two regions.
        return self.lo_region + self.size + 4

    @property
    def src(self) -> int:
        return self.lo_region if self.order == "src_low" else self.hi_region

    @property
    def dst(self) -> int:
        return self.hi_region if self.order == "src_low" else self.lo_region

    @property
    def gap_word(self) -> int:
        return self.lo_region + self.size

    @property
    def range_lo(self) -> int:
        return self.lo_region

    @property
    def range_hi(self) -> int:
        return self.hi_region + self.size - 1

    def base_limit(self) -> tuple[int, int]:
        if self.edge == "low":
            return self.range_lo, SRAM_LIMIT
        if self.edge == "high":
            return SRAM_BASE, self.range_hi
        return self.range_lo, self.range_hi

    def guards(self) -> list[int]:
        """Addresses of the sentinel words the copy must leave unchanged."""
        out = [self.gap_word]
        out += [self.block + 4 * i for i in range(self.g_low // 4)]
        out += [self.range_hi + 1 + 4 * i for i in range(self.g_high // 4)]
        return out


@dataclass
class HashMsg:
    alg: int
    kind: str  # pub, drawn, long
    msg: bytes
    sentinel: int
    swaps: list[int]
    split: int  # 0 when the message has no split form
    src: int = 0
    dst: int = 0


class Plan:
    """Every value of the leaf, drawn from the seed before the first DUT access."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.lines: list[str] = []
        self._leg_a(rng)
        self._leg_b(rng)
        self._leg_c(rng)
        self._leg_d(rng)

    # Leg A ---------------------------------------------------------------
    def _copy(
        self, rng: SepSeededRng, x_args: dict, *, order: bool = True, sentinel: int | None = None
    ) -> CopyXfer:
        """Place, fill and model one copy; ``x_args`` are DmaXfer arguments without bases."""
        probe = DmaXfer(0, 0, **x_args)
        src_fp = probe.src_footprint()
        dst_fp = probe.dst_footprint()
        src_words_n = -(-len(src_fp) // 4)
        dst_words_n = -(-len(dst_fp) // 4) + 2
        src_addr, dst_region = place(rng, [4 * src_words_n, 4 * dst_words_n])
        s = rng.randrange(256) if sentinel is None else sentinel
        words = draw_source_words(rng, src_words_n, s)
        x = DmaXfer(src_addr, dst_region + 4, **x_args)
        regs = list(XFER_ORDER_REGS)
        if order:
            rng.shuffle(regs)
        return CopyXfer(
            x,
            s,
            words,
            src_addr,
            dst_region,
            dst_words_n,
            [dst_region, dst_region + 4 * (dst_words_n - 1)],
            tuple(regs),
        )

    def _leg_a(self, rng: SepSeededRng) -> None:
        cells = list(CELLS)
        rng.shuffle(cells)
        encs = [0, 1, 2] + [rng.randrange(3) for _ in range(len(cells) - 3)]
        rng.shuffle(encs)
        self.cells: list[CellDraw] = []
        for cell, enc in zip(cells, encs):
            si, sw, di, dw = cell
            fixed_side = (not si and not sw) or (not di and not dw)
            min_n = BASIC_PAIRS_MIN_N.get((cell, enc), 1)
            if fixed_side:
                n = 1
            elif min_n > 1:
                n = rng.randrange(min_n, 17)
            else:
                n = 1 if rng.randrange(3) == 0 else rng.randrange(2, 17)
            chunk = 4 * rng.randrange(1, min(16, 1024 // (4 * n)) + 1)
            copy = self._copy(
                rng,
                dict(
                    total=n * chunk,
                    chunk=chunk,
                    width_enc=enc,
                    src_inc=bool(si),
                    src_wrap=bool(sw),
                    dst_inc=bool(di),
                    dst_wrap=bool(dw),
                ),
            )
            self.cells.append(CellDraw(cell, enc, n, chunk, copy))
            self.lines.append(
                f"DRAW leg=A cell={cell_name(cell)} enc={enc} n={n} chunk={chunk} "
                f"bytes={n * chunk} src=0x{copy.x.src_base:08x} dst=0x{copy.x.dst_base:08x} "
                f"sentinel=0x{copy.sentinel:02x} order={','.join(copy.order)}"
            )

    # Leg B ---------------------------------------------------------------
    def _leg_b(self, rng: SepSeededRng) -> None:
        mid = rng.choice((64, 256, 1024, 4096))
        shapes = [(4, 4), (mid, mid), (16384, 4096)]
        for _ in range(2):
            n = rng.randrange(2, 17)
            cmax = min(4096, 16384 // n) // 4
            chunk = 4 * rng.randrange(1, cmax + 1)
            shapes.append((n * chunk, chunk))
        self.mid_total = mid
        self.b_xfers: list[CopyXfer] = []
        for total, chunk in shapes:
            c = self._copy(rng, dict(total=total, chunk=chunk, width_enc=2), order=False)
            self.b_xfers.append(c)
            self.lines.append(
                f"DRAW leg=B total={total} chunk={chunk} n={total // chunk} "
                f"src=0x{c.x.src_base:08x} dst=0x{c.x.dst_base:08x} sentinel=0x{c.sentinel:02x}"
            )

    # Leg C ---------------------------------------------------------------
    def _leg_c(self, rng: SepSeededRng) -> None:
        self.edges: list[EdgeDraw] = []
        for edge in ("low", "high", "both", "guard_low", "guard_high", "guard_both"):
            order = rng.choice(("src_low", "dst_low"))
            size = 4 * rng.randrange(4, 65)
            g_low = 4 * rng.randrange(1, 9) if edge in ("guard_low", "guard_both") else 0
            g_high = 4 * rng.randrange(1, 9) if edge in ("guard_high", "guard_both") else 0
            (block,) = place(rng, [g_low + 2 * size + 4 + g_high])
            s = rng.randrange(256)
            words = draw_source_words(rng, size // 4, s)
            e = EdgeDraw(edge, order, size, g_low, g_high, block, s, words)
            self.edges.append(e)
            base, limit = e.base_limit()
            self.lines.append(
                f"DRAW leg=C edge={edge} order={order} bytes={size} g_low={g_low} "
                f"g_high={g_high} src=0x{e.src:08x} dst=0x{e.dst:08x} base=0x{base:08x} "
                f"limit=0x{limit:08x} sentinel=0x{s:02x}"
            )

    # Leg D ---------------------------------------------------------------
    def _drawn_msg(self, rng: SepSeededRng, alg: int, kind: str, length: int) -> HashMsg:
        s = rng.randrange(256)
        msg = b"".join(w.to_bytes(4, "little") for w in draw_source_words(rng, length // 4, s))
        ks = split_ks(length) if kind != "long" else []
        split = rng.choice(ks) if ks else 0
        return HashMsg(alg, kind, msg, s, [rng.randrange(2)], split)

    def _leg_d(self, rng: SepSeededRng) -> None:
        algs = [256, 384, 512]
        rng.shuffle(algs)
        self.msgs: list[HashMsg] = []
        for alg in algs:
            vec = VEC56 if alg == 256 else VEC112
            swaps = [0, 1]
            rng.shuffle(swaps)
            ks = split_ks(len(vec))
            pub = HashMsg(
                alg, "pub", vec, draw_sentinel_byte(rng, vec), swaps, rng.choice(ks) if ks else 0
            )
            self.msgs.append(pub)
            for _ in range(2):
                if rng.randrange(4) < 3:
                    length = rng.choice(BOUNDARY_LENGTHS)
                else:
                    length = 4 * rng.randrange(1, 65)
                self.msgs.append(self._drawn_msg(rng, alg, "drawn", length))
        long_alg = rng.choice((256, 384, 512))
        self.msgs.append(self._drawn_msg(rng, long_alg, "long", 4 * rng.randrange(256, 1025)))
        for m in self.msgs:
            m.src, m.dst = place(rng, [len(m.msg), len(m.msg)])
            self.lines.append(
                f"DRAW leg=D alg={m.alg} kind={m.kind} len={len(m.msg)} split={m.split} "
                f"swaps={','.join(map(str, m.swaps))} src=0x{m.src:08x} dst=0x{m.dst:08x} "
                f"sentinel=0x{m.sentinel:02x}"
            )


def is_hash_control(alg: int, length: int, split: int, swap: int) -> bool:
    """A Leg D cell that sep_dma_hash_test grades (a control here)."""
    if alg == 256 and length == 56:
        return split == 0 or (split == 2 and swap == 1)
    return alg == 384 and length == 56 and split == 0 and swap == 1


# ---------------------------------------------------------------- ops ------


class _LoggedDmaOps(SepDmaOps):
    """SepDmaOps that records every register write with the tap clock."""

    def __init__(self, test, tap: SepDmaTap) -> None:
        super().__init__(test)
        self.tap = tap
        self.writes: list[tuple[int, int, int, int]] = []  # (clk0, clk1, addr, data)

    async def wr(self, addr: int, data: int) -> None:
        c0 = self.tap.clk
        await super().wr(addr, data)
        self.writes.append((c0, self.tap.clk, addr, data))

    def status_writes(self, clk0: int, clk1: int) -> int:
        return sum(1 for a, b, addr, _ in self.writes if addr == STATUS and b > clk0 and a < clk1)


@dataclass
class XferRecord:
    """What one Leg A or Leg B transfer showed in its window."""

    ev: DmaTapEvents
    clk0: int
    clk1: int
    go_writes: int
    statuses: list[DmaStatus]
    irq_rises: int


@pyuvm.test()
class sep_dma_transfer_matrix_rand_test(sep_base_test):
    """Secure DMA copy and hash matrix over address modes, widths, sizes, range edges and SHA-2."""

    required_evidence = (
        "CHK-DMA-IMAGE",
        "CHK-DMA-BEAT",
        "CHK-DMA-ADDR",
        "CHK-DMA-GEOM",
        "CHK-DMA-DONE-CLR",
        "CHK-DMA-CHUNKDONE",
        "CHK-DMA-CHUNKRISE",
        "CHK-DMA-DONE-ORDER",
        "CHK-DMA-RANGE-OK",
        "CHK-DMA-HASH",
        "CHK-DMA-HASH-VALID",
        "CHK-DMA-HASH-CHAIN",
    )

    # ---- log helpers ------------------------------------------------------
    def _pass(self, chk: str, ok: bool, values: str) -> None:
        line = f"{chk} {'PASS' if ok else 'FAIL'} seed={self.seed} {values}"
        if not ok:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _ctrl_missing(self, chk: str, why: str) -> None:
        line = f"CTRL-MISSING {chk} seed={self.seed} {why}"
        self.logger.error(line)
        raise AssertionError(line)

    def _open(self) -> None:
        open_graded_window(TEST, self.logger)

    def _close(self) -> None:
        close_graded_window(self.logger)

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        plan = Plan(self.seed)
        self.logger.info(
            "PLAN %s seed=%d legA_cells=%d legB_xfers=%d legC_cells=%d legD_msgs=%d",
            TEST,
            self.seed,
            len(plan.cells),
            len(plan.b_xfers),
            len(plan.edges),
            len(plan.msgs),
        )
        for line in plan.lines:
            self.logger.info(line)

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        dut = cocotb.top
        self.tap = SepDmaTap(dut).start()
        self.busy = SepBitWatch(dut.dma_busy_probe_o, name="dma_busy_probe_o").start()
        self.ops = _LoggedDmaOps(self, self.tap)
        self.mem = SepMemWords(self)
        try:
            await self._setup()
            self.irq = SepBitWatch(
                dut.sep_internal_interrupts_probe_o, {"chunk": 9}, name="pic_src10"
            ).start()
            self._open()
            await self._leg_a(plan)
            await self._leg_b(plan)
            await self._leg_c(plan)
            await self._leg_d(plan)
            self._close()
        finally:
            self._close()
            await self.tap.stop()
            await self.busy.stop()
            if getattr(self, "irq", None) is not None:
                await self.irq.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.k)

    async def _setup(self) -> None:
        """Step 2: wide range, ADDR_SPACE_ID, ADDR_HI, STATUS clear, chunk-done interrupt."""
        ops = self.ops
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await ops.set_asid(ASID, ASID)
        await ops.wr(SRC_ADDR_HI, 0)
        await ops.wr(DST_ADDR_HI, 0)
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        await ops.wr(INTR_ENABLE, INTR_CHUNK_DONE)
        self.logger.info(
            "SETUP range=0x%08x..0x%08x valid=1 addr_space_id=0x%02x intr_enable=0x%x",
            SRAM_BASE,
            SRAM_LIMIT,
            asid_word(ASID, ASID),
            INTR_CHUNK_DONE,
        )

    # ---- shared transfer pieces -------------------------------------------
    async def _fill_copy(self, c: CopyXfer) -> None:
        await self.mem.fill(c.src_addr, c.src_words)
        await self.mem.fill(c.dst_region, [sentinel_word(c.sentinel)] * c.dst_region_words)

    async def _program(self, c: CopyXfer) -> None:
        x = c.x
        await self.ops.program_transfer(
            src=x.src_base,
            dst=x.dst_base,
            total=x.total,
            chunk=x.chunk,
            width_enc=x.width_enc,
            src_inc=x.src_inc,
            src_wrap=x.src_wrap,
            dst_inc=x.dst_inc,
            dst_wrap=x.dst_wrap,
            order=list(c.order),
        )

    def _record(self, m_tap, m_irq, go_writes: int, statuses: list[DmaStatus]) -> XferRecord:
        m_end = self.tap.mark()
        return XferRecord(
            self.tap.between(m_tap, m_end),
            m_tap.clk,
            m_end.clk,
            go_writes,
            statuses,
            self.irq.rises_since(m_irq, "chunk"),
        )

    def _check_chunkrise(self, rec: XferRecord, n: int, tag: str) -> None:
        ev = rec.ev
        rises = ev.rises("chunk_done")
        falls = ev.falls("chunk_done")
        done_rises = ev.rises("done")
        r = len(rises)
        need = min(r, n - 1)
        hw_falls = 0
        for i in range(need):
            c = rises[i]
            nxt = [x for x in rises[i + 1 :] + done_rises if x > c]
            end = min(nxt) if nxt else rec.clk1 + 1
            if any(c < f < end for f in falls):
                hw_falls += 1
        sw = self.ops.status_writes(rec.clk0, rec.clk1)
        ok_count = (r == 0) if n == 1 else (n - 1 <= r <= n)
        ok = ok_count and hw_falls >= need and sw == 0
        self._pass(
            "CHK-DMA-CHUNKRISE",
            ok,
            f"n={n} rises={r} hw_falls={hw_falls} last_rise_exempt={int(n > 1 and r == n)} "
            f"status_writes_in_window={sw} {tag} rise_clks={rises} fall_clks={falls}",
        )

    def _check_done_order(self, rec: XferRecord, total: int, tag: str) -> None:
        ev = rec.ev
        aw, b = len(ev.aw), len(ev.b)
        done_rises = ev.rises("done")
        last_b = max((x.clk for x in ev.b), default=None)
        early = [d for d in done_rises if last_b is None or d <= last_b]
        bad_resp = sum(1 for x in ev.b if x.resp != 0)
        ok = b > 0 and b == aw and bool(done_rises) and not early
        self._pass(
            "CHK-DMA-DONE-ORDER",
            ok,
            f"bytes={total} aw={aw} b={b} done_rises={len(done_rises)} last_b_clk={last_b} "
            f"done_rise_clk={done_rises[-1] if done_rises else None} early_rises={len(early)} "
            f"bresp_nonzero={bad_resp} {tag}",
        )

    async def _read_regs(self) -> tuple[DmaStatus, int, int]:
        st = await self.ops.read_status()
        err = await self.ops.rd(ERROR_CODE)
        ctl = await self.ops.rd(CONTROL)
        return st, err, ctl

    async def _wait_idle_done(self, tag: str) -> DmaStatus:
        return await self.ops.poll_status(
            lambda s: bool(s.done and not s.busy), 50, f"DONE=1 BUSY=0 {tag}"
        )

    # ---- Leg A ------------------------------------------------------------
    async def _leg_a(self, plan: Plan) -> None:
        ops = self.ops
        for cd in plan.cells:
            c, x = cd.copy, cd.copy.x
            tag = f"cell={cell_name(cd.cell)} enc={cd.enc}"
            await self._fill_copy(c)
            await self._program(c)
            m_tap, m_irq = self.tap.mark(), self.irq.mark()
            await ops.go(opcode=OP_COPY, initial=1)
            # The poll bound scales with the transaction count of the cell.
            res = await ops.run_to_done(
                poll_size(4 * x.n_txn), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=f" {tag}"
            )
            if res.status.done:
                await self._wait_idle_done(tag)
            rec = self._record(m_tap, m_irq, res.go_writes, res.statuses)
            self.logger.info(
                "LEGA %s statuses=%s",
                tag,
                rle([f"b{s.busy}d{s.done}c{s.chunk_done}e{s.error}" for s in res.statuses]),
            )
            st, err, _ = await self._read_regs()
            got_dst = await self.mem.read(c.dst_region, c.dst_region_words)
            got_src = await self.mem.read(c.src_addr, len(c.src_words))
            exp = c.expected_dst()
            mism = sum(1 for g, e in zip(got_dst[1:-1], exp[1:-1]) if g != e)
            sw = sentinel_word(c.sentinel)
            guard_ok = int(got_dst[0] == sw and got_dst[-1] == sw)
            src_ok = int(got_src == c.src_words)
            fst = field_compare(st.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR)
            fer = field_compare(err, 0, ERROR_CODE_MASK)
            if mism:
                first = next(i for i, (g, e) in enumerate(zip(got_dst, exp)) if g != e and 0 < i)
                self.logger.error(
                    "LEGA %s first mismatch word %d @0x%08x got=0x%08x exp=0x%08x",
                    tag,
                    first,
                    c.dst_region + 4 * first,
                    got_dst[first],
                    exp[first],
                )
            ok = mism == 0 and guard_ok and src_ok and fst.ok and fer.ok
            self._pass(
                "CHK-DMA-IMAGE",
                ok,
                f"cell={cell_name(cd.cell)} enc={cd.enc} w={x.w} chunk={cd.chunk} n={cd.n} "
                f"bytes={x.total} mem_mismatch={mism} guard_ok={guard_ok} error={st.error} "
                f"go_writes={res.go_writes} src_ok={src_ok} {ff('status', fst)} "
                f"{ff('error_code', fer)}",
            )
            self._check_beats(cd, rec)
            self._check_chunkrise(rec, cd.n, tag)
            self._check_done_order(rec, x.total, tag)
            await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)

    def _check_beats(self, cd: CellDraw, rec: XferRecord) -> None:
        x, ev = cd.copy.x, rec.ev
        n_txn = x.n_txn
        ar, aw, wb = ev.ar, ev.aw, ev.w
        axlen_nz = sum(1 for b in ar + aw if b.len != 0)
        wstrb_bad = sum(1 for b in wb if b.strb is None or bin(b.strb).count("1") != x.w)
        rstep_bad = 0
        if cd.enc == 2 and x.src_inc:
            for i in range(1, min(len(ar), n_txn)):
                if x.chunk_of(i) == x.chunk_of(i - 1):
                    if ar[i].addr is None or ar[i - 1].addr is None:
                        rstep_bad += 1
                    elif ar[i].addr - ar[i - 1].addr != 4:
                        rstep_bad += 1
        name = cell_name(cd.cell)
        ok = (
            len(ar) == n_txn
            and len(aw) == n_txn
            and len(wb) == n_txn
            and n_txn > 0
            and axlen_nz == 0
            and wstrb_bad == 0
            and rstep_bad == 0
        )
        self._pass(
            "CHK-DMA-BEAT",
            ok,
            f"cell={name} enc={cd.enc} w={x.w} bytes={x.total} ar={len(ar)} aw={len(aw)} "
            f"axlen_nonzero={axlen_nz} wstrb_bad={wstrb_bad} rstep_bad={rstep_bad} "
            f"w_beats={len(wb)} expect_beats={n_txn}",
        )
        exp_ar, exp_aw, exp_strb = x.ar_addrs(), x.aw_addrs(), x.wstrbs()
        amask = 0xFFFF_FFFF if cd.enc == 2 else 0xFFFF_FFFC
        addr_mm = abs(len(ar) - n_txn) + abs(len(aw) - n_txn)
        for got, exp in ((ar, exp_ar), (aw, exp_aw)):
            for b, e in zip(got, exp):
                if b.addr is None or (b.addr & amask) != (e & amask):
                    addr_mm += 1
        strb_mm = 0
        low_eq = 0
        if cd.enc != 2:
            strb_mm = abs(len(wb) - n_txn)
            for b, e in zip(wb, exp_strb):
                if b.strb != e:
                    strb_mm += 1
            for got, exp in ((ar, exp_ar), (aw, exp_aw)):
                low_eq += sum(
                    1 for b, e in zip(got, exp) if b.addr is not None and b.addr & 3 == e & 3
                )
            self.logger.info(
                "OBS-DMA-ADDR-LOW LOG seed=%d enc=%d beats=%d low_eq_model=%d cell=%s",
                self.seed,
                cd.enc,
                len(ar) + len(aw),
                low_eq,
                name,
            )
        if addr_mm or strb_mm:
            for i, (b, e) in enumerate(zip(ar, exp_ar)):
                if b.addr is None or (b.addr & amask) != (e & amask):
                    self.logger.error("AR %d got=%s exp=0x%08x", i, b.addr, e)
                    break
            for i, (b, e) in enumerate(zip(aw, exp_aw)):
                if b.addr is None or (b.addr & amask) != (e & amask):
                    self.logger.error("AW %d got=%s exp=0x%08x", i, b.addr, e)
                    break
        self._pass(
            "CHK-DMA-ADDR",
            n_txn > 0 and addr_mm == 0 and strb_mm == 0,
            f"cell={name} enc={cd.enc} beats={len(ar) + len(aw)} addr_mismatch={addr_mm} "
            f"strb_lane_mismatch={strb_mm} addr_mask=0x{amask:08x}",
        )

    # ---- Leg B ------------------------------------------------------------
    async def _poll_b(
        self, total: int, m_busy, want_ctrl: bool, tag: str
    ) -> tuple[DmaStatus, int, list[tuple[DmaStatus, int]], int | None]:
        """Steps 9 and 10: poll to DONE=1 BUSY=0 after a BUSY rise, with the re-GO rule.

        Returns the last STATUS, the GO-write count, every (STATUS, probe level)
        read, and the GO bit of a CONTROL read that ran entirely at BUSY=1
        (None when no such read landed).
        """
        ops = self.ops
        bound = ops.done_bound(poll_size(total))
        go_writes = 1
        reads: list[tuple[DmaStatus, int]] = []
        ctrl_go: int | None = None
        tries = 0
        for _ in range(bound):
            if want_ctrl and ctrl_go != 1 and tries < CTRL_READ_TRIES and self.busy.level() == 1:
                m = self.busy.mark()
                v = await ops.rd(CONTROL)
                tries += 1
                if self.busy.level() == 1 and not self.busy.fall_clks_since(m):
                    ctrl_go = int(bool(v & GO_MASK))
                    self.logger.info(
                        "LEGB %s CONTROL=0x%08x go=%d busy_through_read=1", tag, v, ctrl_go
                    )
            st = await ops.read_status()
            reads.append((st, int(self.busy.level() or 0)))
            if st.done and not st.busy and self.busy.rose_since(m_busy):
                return st, go_writes, reads, ctrl_go
            if st.error or st.aborted:
                return st, go_writes, reads, ctrl_go
            if st.chunk_done and not st.done and not st.busy:
                m = self.busy.mark()
                value = (ops.last_control & ~control_word(initial=1)) | GO_MASK
                await ops.wr(CONTROL, value)
                go_writes += 1
                await self.busy.wait_rise(m, BUSY_RISE_BOUND)
        msg = (
            f"FAIL-DMA-TIMEOUT {tag}: DONE=1 BUSY=0 after a BUSY rise not seen in {bound} "
            f"STATUS reads (total={total}, go_writes={go_writes})"
        )
        self.logger.error(msg)
        raise DmaTimeout(msg)

    async def _leg_b(self, plan: Plan) -> None:
        ops = self.ops
        single_runs: list[tuple[int, int, int]] = []  # (total, n, polls_with_chunk_done)
        multi_polls = 0
        multi_chunk_polls = 0
        multi_irq_rises = 0
        ctrl_go_busy_seen = False
        for i, c in enumerate(plan.b_xfers):
            x = c.x
            n = x.n_chunks
            tag = f"total={x.total} chunk={x.chunk}"
            await self._fill_copy(c)
            await self._program(c)
            await ops.wr(STATUS, ST_CHUNK_DONE)
            pre_go_done = None
            if i > 0:
                pre = await ops.read_status()
                pre_go_done = pre.done
                self.logger.info("LEGB %s pre-GO %s", tag, pre.fmt())
            m_tap, m_irq, m_busy = self.tap.mark(), self.irq.mark(), self.busy.mark()
            await ops.go(opcode=OP_COPY, initial=1)
            st, go_writes, reads, ctrl_go = await self._poll_b(
                x.total, m_busy, x.total >= LONG_TOTAL, tag
            )
            rec = self._record(m_tap, m_irq, go_writes, [s for s, _ in reads])
            busy_trace = (
                f"rises={self.busy.rise_clks_since(m_busy)} "
                f"falls={self.busy.fall_clks_since(m_busy)} from_clk={m_busy.clk}"
            )
            self.logger.info(
                "LEGB %s go_writes=%d reads=%s busy_probe %s",
                tag,
                go_writes,
                rle([f"b{s.busy}d{s.done}c{s.chunk_done}p{p}" for s, p in reads]),
                busy_trace,
            )
            st2, err, ctl = await self._read_regs()
            got = await self.mem.read(c.dst_region, c.dst_region_words)
            exp = c.expected_dst()
            mism = sum(1 for g, e in zip(got[1:-1], exp[1:-1]) if g != e)
            sw = sentinel_word(c.sentinel)
            guard_ok = got[0] == sw and got[-1] == sw
            fst = field_compare(st2.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR)
            fgo = field_compare(ctl, 0, GO_MASK)
            fer = field_compare(err, 0, ERROR_CODE_MASK)
            if x.total >= LONG_TOTAL and ctrl_go == 1:
                ctrl_go_busy_seen = True
            cgb = "1" if (x.total >= LONG_TOTAL and ctrl_go == 1) else "-"
            ok = fst.ok and fgo.ok and fer.ok and mism == 0 and guard_ok
            self._pass(
                "CHK-DMA-GEOM",
                ok,
                f"total={x.total} chunk={x.chunk} n={n} go_writes={go_writes} done={st2.done} "
                f"busy={st2.busy} go={int(bool(ctl & GO_MASK))} error={st2.error} "
                f"mem_mismatch={mism} control_go_busy={cgb} guard_ok={int(guard_ok)} "
                f"{ff('status', fst)} {ff('control', fgo)} {ff('error_code', fer)}",
            )
            if i > 0 and x.total >= LONG_TOTAL:
                if pre_go_done != 1:
                    self._ctrl_missing("CHK-DMA-DONE-CLR", f"{tag} pre_go_done={pre_go_done}")
                k0 = sum(1 for s, _ in reads if s.busy and not s.done)
                self._pass(
                    "CHK-DMA-DONE-CLR",
                    k0 >= 1,
                    f"total={x.total} pre_go_done=1 busy_reads_done0={k0} "
                    f"busy_reads={sum(1 for s, _ in reads if s.busy)}",
                )
            if n == 1:
                single_runs.append((x.total, n, sum(1 for s, _ in reads if s.chunk_done)))
            else:
                multi_polls += len(reads)
                multi_chunk_polls += sum(1 for s, _ in reads if s.chunk_done)
                multi_irq_rises += rec.irq_rises
            self._check_chunkrise(rec, n, tag)
            self._check_done_order(rec, x.total, tag)
        if not ctrl_go_busy_seen:
            self._ctrl_missing(
                "CHK-DMA-GEOM", "no CONTROL read returned GO=1 at BUSY=1 on a total >= 1024"
            )
        if multi_chunk_polls == 0 and multi_irq_rises == 0:
            self._ctrl_missing(
                "CHK-DMA-CHUNKDONE",
                f"multi-chunk polls={multi_polls} with CHUNK_DONE=1: 0, PIC source 10 rises: 0",
            )
        for total, n, k in single_runs:
            self._pass(
                "CHK-DMA-CHUNKDONE",
                k == 0,
                f"n={n} single=1 polls_with_chunk_done={k} "
                f"control_multi_polls={multi_chunk_polls} "
                f"control_chunk_irq_rises={multi_irq_rises} total={total}",
            )

    # ---- Leg C ------------------------------------------------------------
    async def _edge_copy(self, e: EdgeDraw, base: int, limit: int, tag: str):
        ops = self.ops
        sw = sentinel_word(e.sentinel)
        await self.mem.fill(e.src, e.src_words)
        await self.mem.fill(e.dst, [sw] * (e.size // 4))
        for g in e.guards():
            await self.mem.fill(g, [sw])
        await ops.program_range(base, limit, valid=True)
        await ops.program_transfer(
            src=e.src, dst=e.dst, total=e.size, chunk=e.size, width_enc=2, order=XFER_ORDER_REGS
        )
        await ops.go(opcode=OP_COPY, initial=1)
        res = await ops.run_to_done(
            poll_size(e.size), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=tag
        )
        if res.status.done:
            await self._wait_idle_done(tag)
        st, err, _ = await self._read_regs()
        got = await self.mem.read(e.dst, e.size // 4)
        mism = sum(1 for g, s in zip(got, e.src_words) if g != s)
        guards_bad = 0
        for g in e.guards():
            (v,) = await self.mem.read(g, 1)
            guards_bad += int(v != sw)
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        fst = field_compare(st.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR)
        fer = field_compare(err, 0, ERROR_CODE_MASK)
        return st, fst, fer, mism, guards_bad

    async def _leg_c(self, plan: Plan) -> None:
        await self.ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        for e in plan.edges:
            base, limit = e.base_limit()
            tag = f"edge={e.edge} order={e.order}"
            st, fst, fer, mism, gbad = await self._edge_copy(e, base, limit, tag)
            # Control: the same regions under the wide range of step 2.
            self._close()
            cst, cfst, cfer, cmism, cgbad = await self._edge_copy(
                e, SRAM_BASE, SRAM_LIMIT, f"{tag} control_wide"
            )
            self._open()
            control_wide = int(cfst.ok and cfer.ok and cmism == 0 and cgbad == 0)
            if not control_wide:
                self._ctrl_missing(
                    "CHK-DMA-RANGE-OK",
                    f"{tag} wide-range control failed: {ff('status', cfst)} "
                    f"{ff('error_code', cfer)} mem_mismatch={cmism} guards_bad={cgbad}",
                )
            edge = "guard" if e.edge.startswith("guard") else e.edge
            ok = fst.ok and fer.ok and mism == 0 and gbad == 0
            self._pass(
                "CHK-DMA-RANGE-OK",
                ok,
                f"edge={edge} order={e.order} base=0x{base:08x} limit=0x{limit:08x} "
                f"done={st.done} error={st.error} mem_mismatch={mism} control_wide={control_wide} "
                f"cell={e.edge} guards_bad={gbad} {ff('status', fst)} {ff('error_code', fer)}",
            )

    # ---- Leg D ------------------------------------------------------------
    async def _hash_run(
        self, m: HashMsg, split: int, swap: int, run_idx: int, ctrl_state: dict
    ) -> tuple[list[int], dict]:
        """Steps 17 to 22 for one form and swap value; returns the digest words read."""
        ops = self.ops
        alg_op, _, n_words = ALGS[m.alg]
        length = len(m.msg)
        chunk = length // split if split else length
        k = split or 1
        tag = f"alg={m.alg} kind={m.kind} len={length} split={split} swap={swap}"
        await self.mem.fill(m.dst, [sentinel_word(m.sentinel)] * (length // 4))
        await ops.program_transfer(
            src=m.src, dst=m.dst, total=length, chunk=chunk, width_enc=2, order=XFER_ORDER_REGS
        )
        if run_idx >= 1:
            pre = await ops.read_status()
            self.logger.info("LEGD %s pre-GO %s", tag, pre.fmt())
            if run_idx == 1:
                ctrl_state["before_second"] = pre.digest_valid
        await ops.go(opcode=alg_op, digest_swap=swap, initial=1)
        try:
            res = await ops.run_to_done(
                poll_size(length),
                busy=self.busy,
                w1c_chunk_done=True,
                busy_bound=BUSY_RISE_BOUND,
                max_go=k,
                tag=f" {tag}",
            )
        except DmaTimeout:
            raise
        except AssertionError as exc:
            msg = f"FAIL-DMA-TIMEOUT {tag}: more than {k} GO writes ({exc})"
            self.logger.error(msg)
            raise DmaTimeout(msg) from exc
        if res.status.done:
            await self._wait_idle_done(tag)
        busy_reads = [s for s in res.statuses if s.busy]
        self.logger.info(
            "LEGD %s go_writes=%d busy_reads=%s",
            tag,
            res.go_writes,
            rle([f"b{s.busy}d{s.done}c{s.chunk_done}v{s.digest_valid}" for s in busy_reads]),
        )
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        valid_after = 0
        for _ in range(VALID_POLL_BOUND):
            if (await ops.read_status()).digest_valid:
                valid_after = 1
                break
        st, err, _ = await self._read_regs()
        words = await ops.read_digest(n_words)
        dst = await self.mem.read(m.dst, length // 4)
        copy_mm = sum(
            1 for i, w in enumerate(dst) if w != int.from_bytes(m.msg[4 * i : 4 * i + 4], "little")
        )
        info = dict(
            tag=tag,
            split=split,
            swap=swap,
            go_writes=res.go_writes,
            done=res.status.done,
            error=st.error,
            err=err,
            busy_reads=len(busy_reads),
            busy_valid0=sum(1 for s in busy_reads if not s.digest_valid),
            valid_after=valid_after,
            copy_mm=copy_mm,
        )
        return words, info

    async def _leg_d(self, plan: Plan) -> None:
        run_idx = 0
        ctrl_state: dict = {}
        valid_lines: list[tuple[HashMsg, dict]] = []
        for m in plan.msgs:
            length = len(m.msg)
            sw = sentinel_word(m.sentinel)
            await self.mem.fill(
                m.src, [int.from_bytes(m.msg[i : i + 4], "little") for i in range(0, length, 4)]
            )
            await self.mem.fill(m.dst, [sw] * (length // 4))
            forms = [0] + ([m.split] if m.split else [])
            digests: dict[tuple[int, int], tuple[list[int], bool]] = {}
            for split in forms:
                for swap in m.swaps:
                    control = is_hash_control(m.alg, length, split, swap)
                    if control:
                        self._close()
                    words, info = await self._hash_run(m, split, swap, run_idx, ctrl_state)
                    run_idx += 1
                    gold = golden_words(m.alg, m.msg, swap)
                    mism = sum(1 for g, e in zip(words, gold) if g != e) + abs(
                        len(words) - len(gold)
                    )
                    fer = field_compare(info["err"], 0, ERROR_CODE_MASK)
                    digests[(split, swap)] = (words, control)
                    if control:
                        self.logger.info(
                            "OBS-DMA-HASH-CTRL LOG seed=%d alg=%d len=%d split=%d swap=%d "
                            "words=%d mismatch=%d copy_mismatch=%d error=%d",
                            self.seed,
                            m.alg,
                            length,
                            split,
                            swap,
                            len(words),
                            mism,
                            info["copy_mm"],
                            info["error"],
                        )
                    else:
                        if mism:
                            self.logger.error(
                                "LEGD %s digest got=%s exp=%s",
                                info["tag"],
                                [f"{w:08x}" for w in words],
                                [f"{w:08x}" for w in gold],
                            )
                        ok = (
                            mism == 0
                            and info["copy_mm"] == 0
                            and info["done"] == 1
                            and info["error"] == 0
                            and fer.ok
                        )
                        self._pass(
                            "CHK-DMA-HASH",
                            ok,
                            f"alg={m.alg} len={length} split={split} swap={swap} "
                            f"words={len(gold)} mismatch={mism} copy_mismatch={info['copy_mm']} "
                            f"go_writes={info['go_writes']} {ff('error_code', fer)}",
                        )
                    valid_lines.append((m, info))
                    if control:
                        self._open()
            for swap in m.swaps:
                if not m.split:
                    continue
                a, ca = digests[(0, swap)]
                b, cb = digests[(m.split, swap)]
                if ca or cb:
                    continue
                self._pass(
                    "CHK-DMA-HASH-CHAIN",
                    a == b,
                    f"alg={m.alg} len={length} split={m.split} single_eq_split={int(a == b)} "
                    f"swap={swap}",
                )
        if ctrl_state.get("before_second") != 1:
            self._ctrl_missing(
                "CHK-DMA-HASH-VALID",
                f"SHA2_DIGEST_VALID before the GO of the second run = "
                f"{ctrl_state.get('before_second')}",
            )
        for m, info in valid_lines:
            length = len(m.msg)
            graded_clear = length >= LONG_TOTAL
            if graded_clear and info["busy_reads"] == 0:
                self._ctrl_missing(
                    "CHK-DMA-HASH-VALID", f"{info['tag']}: no STATUS read landed at BUSY=1"
                )
            ok = info["valid_after"] == 1 and (not graded_clear or info["busy_valid0"] >= 1)
            self._pass(
                "CHK-DMA-HASH-VALID",
                ok,
                f"alg={m.alg} len={length} "
                f"busy_reads_valid0={info['busy_valid0'] if graded_clear else '-'} "
                f"after_last={info['valid_after']} control_before_second=1 "
                f"kind={m.kind} split={info['split']} swap={info['swap']}",
            )
