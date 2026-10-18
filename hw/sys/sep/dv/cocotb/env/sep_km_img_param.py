# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded KM ROM parameter blocks of the scripted Key Manager images.

A scripted KM image reads the drawn configuration of its leaf from a parameter
block at a fixed KM ROM word address. ``dv_sim_prestage.py`` stages a copy of
the committed image with the block of the leaf seed appended at that address,
and the image load ``tb_backdoor_mem`` (``+km_rom_hex``) preloads the copy into
the KM ROM macro at t=0, before the KM leaves reset. The test calls the same
``plan(item, seed)`` at runtime for its golden, so the staged block and the
golden are one function of the seed.

Block layout, one 32-bit word per entry, from KM ROM word ``PARAM_BASE_WORD``:

    word 0          PARAM_MAGIC
    word 1          (PARAM_VERSION << 16) | block id
    word 2          payload length n (words)
    words 3..n+2    payload (the layout of each block below)
    word n+3        check word: XOR of words 0..n+2

No cocotb import: the pre-sim staging hook loads this module by path.

The stream is not a CSPRNG. Every key and word here is a labelled test vector
that lives only in the simulation, and no per-seed value is evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from sep_seeded_rng import SepSeededRng

T_SCR = "sep_km_sram_scrambler_key_rand_test"
T_MBOX_KM = "sep_km_mailbox_km_side_rand_test"
TESTS = (T_SCR, T_MBOX_KM)

# The KM ROM holds 4096 words (architecture.adoc, Parameters: 16 KB ROM). The
# block takes the last 256 words; an image must end below PARAM_BASE_WORD.
ROM_WORDS = 4096
PARAM_BASE_WORD = 0xF00
PARAM_MAX_WORDS = ROM_WORDS - PARAM_BASE_WORD
PARAM_MAGIC = 0x4B4D_5052
PARAM_VERSION = 1
BLOCK_SCR = 0x1
BLOCK_MBOX_KM = 0x2

WORD_MASK = 0xFFFF_FFFF
# KM SRAM byte window of the drawn stores: regions 1 to 31, word aligned. Region
# 0 holds the image data and is never a drawn address.
SRAM_DRAW_LO = 0x8400
SRAM_DRAW_HI = 0xFFFC
SRAM_REGION_BYTES = 0x400
MBOX_DEPTH = 16

# A draw that cannot find a fresh value in this many tries is a generator bug.
_DRAW_TRIES = 64


def _fresh(rng: SepSeededRng, taken: set[int], bits: int = 32) -> int:
    """A non-zero value of ``bits`` bits that is not in ``taken``."""
    for _ in range(_DRAW_TRIES):
        v: int = rng.getrandbits(bits)
        if v != 0 and v not in taken:
            taken.add(v)
            return v
    raise RuntimeError(f"no fresh value in {_DRAW_TRIES} draws")


def _fresh_addr(rng: SepSeededRng, taken: set[int]) -> int:
    for _ in range(_DRAW_TRIES):
        a: int = rng.randrange(SRAM_DRAW_LO, SRAM_DRAW_HI + 4, 4)
        if a not in taken:
            taken.add(a)
            return a
    raise RuntimeError(f"no fresh SRAM address in {_DRAW_TRIES} draws")


def _key_pair(rng: SepSeededRng) -> tuple[int, int]:
    """kA and kB: non-zero, and every byte of kA differs from the same byte of kB."""
    for _ in range(_DRAW_TRIES):
        ka = rng.getrandbits(32)
        kb = rng.getrandbits(32)
        if ka and kb and all(((ka ^ kb) >> (8 * i)) & 0xFF for i in range(4)):
            return ka, kb
    raise RuntimeError("no key pair with every byte different")


def word_parity(w: int) -> int:
    """Per-byte odd parity nibble of a KM ROM word (tests/km_fw/gen_parhex.py)."""
    p = 0
    for i in range(4):
        b = (w >> (8 * i)) & 0xFF
        p |= (1 ^ (bin(b).count("1") & 1)) << i
    return p


@dataclass
class ScrPlan:
    """IMG-SCR configuration (sep_km_sram_scrambler_key_rand_test, Randomization)."""

    seed: int
    ka: int
    kb: int
    addrs8: list[int]
    data8: list[int]
    order8: list[int]
    addrs64: list[int]
    data64: list[int]
    addrs_lock: list[int]
    data_lock: list[int]

    # Payload offsets (words from the start of the payload).
    OFF_KA = 0
    OFF_KB = 1
    OFF_ADDRS8 = 2
    OFF_DATA8 = 10
    OFF_ORDER8 = 18
    OFF_ADDRS64 = 19
    OFF_DATA64 = 83
    OFF_ADDRS_LOCK = 147
    OFF_DATA_LOCK = 149
    PAYLOAD_WORDS = 151

    def payload(self) -> list[int]:
        order = 0
        for i, idx in enumerate(self.order8):
            order |= (idx & 0xF) << (4 * i)
        words = (
            [self.ka, self.kb]
            + self.addrs8
            + self.data8
            + [order]
            + self.addrs64
            + self.data64
            + self.addrs_lock
            + self.data_lock
        )
        if len(words) != self.PAYLOAD_WORDS:
            raise RuntimeError(f"IMG-SCR payload has {len(words)} words")
        return words


@dataclass
class MboxPlan:
    """IMG-MBOX-KM configuration (sep_km_mailbox_km_side_rand_test, Randomization).

    The image writes every outbound word from the block. The inbound words come
    from the host, which draws them from the same plan at runtime.
    """

    seed: int
    n_drawn: int
    m_drawn: int
    err_first: list[int]
    flush_order: list[int]
    flush_one_fifo: list[int]
    irq_enable_s: int
    src_order: list[int]
    out_pass: list[list[int]]
    out_overflow: list[int]
    out_flush: list[list[int]]
    out_irq: list[list[int]]
    in_pass: list[list[int]] = field(default_factory=list)
    in_flush: list[list[int]] = field(default_factory=list)

    # The outbound pass counts in order: 16, 1, 15 and the drawn N.
    # Flush cells: 0 KM both empty, 1 KM one non-empty, 2 KM both non-empty,
    # 3 SEP both empty, 4 SEP one non-empty, 5 SEP both non-empty.
    FLUSH_CELLS = 6
    FLUSH_FILL = 4
    OVERFLOW_WORDS = 18
    IRQ_RUN_WORDS = MBOX_DEPTH + 2
    OFF_N = 0
    OFF_M = 1
    OFF_ERR_FIRST = 2
    OFF_FLUSH_ORDER = 3
    OFF_FLUSH_ONE = 4
    OFF_IRQ_S = 5
    OFF_SRC_ORDER = 6
    OFF_OUT_PASS = 7  # 16 + 1 + 15 + 16 words; the drawn pass uses its first N
    OFF_OVERFLOW = OFF_OUT_PASS + 48
    OFF_OUT_FLUSH = OFF_OVERFLOW + OVERFLOW_WORDS
    OFF_OUT_IRQ = OFF_OUT_FLUSH + FLUSH_CELLS * FLUSH_FILL
    PAYLOAD_WORDS = OFF_OUT_IRQ + 2 * IRQ_RUN_WORDS

    def payload(self) -> list[int]:
        err = self.err_first[0] | (self.err_first[1] << 1)
        flush_order = 0
        for i, cell in enumerate(self.flush_order):
            flush_order |= (cell & 0x7) << (3 * i)
        flush_one = self.flush_one_fifo[0] | (self.flush_one_fifo[1] << 1)
        src_order = 0
        for i, src in enumerate(self.src_order):
            src_order |= (src & 0x3) << (2 * i)
        drawn = self.out_pass[3] + [0] * (MBOX_DEPTH - len(self.out_pass[3]))
        words = (
            [self.n_drawn, self.m_drawn, err, flush_order, flush_one, self.irq_enable_s, src_order]
            + self.out_pass[0]
            + self.out_pass[1]
            + self.out_pass[2]
            + drawn
            + self.out_overflow
            + [w for cell in self.out_flush for w in cell]
            + [w for run in self.out_irq for w in run]
        )
        if len(words) != self.PAYLOAD_WORDS:
            raise RuntimeError(f"IMG-MBOX-KM payload has {len(words)} words")
        return words


def _scr_plan(seed: int) -> ScrPlan:
    rng = SepSeededRng(seed)
    ka, kb = _key_pair(rng)
    taken_addr: set[int] = set()
    # addrs8[0], addrs8[1]: an adjacent pair, which holds the equal plaintext P.
    # addrs8[2], addrs8[3]: one offset in two different 1 KiB regions.
    for _ in range(_DRAW_TRIES):
        a0 = rng.randrange(SRAM_DRAW_LO, SRAM_DRAW_HI, 4)
        if a0 not in taken_addr and a0 + 4 not in taken_addr:
            break
    else:
        raise RuntimeError("no adjacent SRAM pair")
    taken_addr.update((a0, a0 + 4))
    regions = list(
        range(SRAM_DRAW_LO // SRAM_REGION_BYTES, (SRAM_DRAW_HI // SRAM_REGION_BYTES) + 1)
    )
    for _ in range(_DRAW_TRIES):
        r1, r2 = rng.sample(regions, 2)
        off = rng.randrange(0, SRAM_REGION_BYTES, 4)
        b1, b2 = r1 * SRAM_REGION_BYTES + off, r2 * SRAM_REGION_BYTES + off
        if b1 not in taken_addr and b2 not in taken_addr:
            break
    else:
        raise RuntimeError("no same-offset SRAM pair")
    taken_addr.update((b1, b2))
    addrs8 = [a0, a0 + 4, b1, b2] + [_fresh_addr(rng, taken_addr) for _ in range(4)]
    taken_data: set[int] = set()
    p = _fresh(rng, taken_data)
    data8 = [p, p] + [_fresh(rng, taken_data) for _ in range(6)]
    order8 = list(range(8))
    rng.shuffle(order8)
    addrs64 = [_fresh_addr(rng, taken_addr) for _ in range(64)]
    taken64: set[int] = set()
    data64 = [_fresh(rng, taken64) for _ in range(64)]
    addrs_lock = [_fresh_addr(rng, taken_addr) for _ in range(2)]
    taken_lock: set[int] = set()
    data_lock = [_fresh(rng, taken_lock) for _ in range(2)]
    return ScrPlan(
        seed=seed,
        ka=ka,
        kb=kb,
        addrs8=addrs8,
        data8=data8,
        order8=order8,
        addrs64=addrs64,
        data64=data64,
        addrs_lock=addrs_lock,
        data_lock=data_lock,
    )


def _words(rng: SepSeededRng, n: int) -> list[int]:
    """``n`` non-zero words, pairwise different (one pass)."""
    taken: set[int] = set()
    return [_fresh(rng, taken) for _ in range(n)]


def _mbox_plan(seed: int) -> MboxPlan:
    rng = SepSeededRng(seed)
    n_drawn = rng.randrange(1, MBOX_DEPTH + 1)
    m_drawn = rng.randrange(1, MBOX_DEPTH + 1)
    err_first = [rng.getrandbits(1), rng.getrandbits(1)]
    flush_order = list(range(MboxPlan.FLUSH_CELLS))
    rng.shuffle(flush_order)
    flush_one_fifo = [rng.getrandbits(1), rng.getrandbits(1)]
    irq_enable_s = rng.randrange(0, 0x20)
    src_order = list(range(4))
    rng.shuffle(src_order)
    out_pass = [_words(rng, n) for n in (MBOX_DEPTH, 1, MBOX_DEPTH - 1, n_drawn)]
    out_overflow = _words(rng, MboxPlan.OVERFLOW_WORDS)
    out_flush = [_words(rng, MboxPlan.FLUSH_FILL) for _ in range(MboxPlan.FLUSH_CELLS)]
    out_irq = [_words(rng, MboxPlan.IRQ_RUN_WORDS) for _ in range(2)]
    in_pass = [_words(rng, m) for m in (MBOX_DEPTH, 1, MBOX_DEPTH - 1, m_drawn)]
    in_flush = [_words(rng, MboxPlan.FLUSH_FILL) for _ in range(MboxPlan.FLUSH_CELLS)]
    return MboxPlan(
        seed=seed,
        n_drawn=n_drawn,
        m_drawn=m_drawn,
        err_first=err_first,
        flush_order=flush_order,
        flush_one_fifo=flush_one_fifo,
        irq_enable_s=irq_enable_s,
        src_order=src_order,
        out_pass=out_pass,
        out_overflow=out_overflow,
        out_flush=out_flush,
        out_irq=out_irq,
        in_pass=in_pass,
        in_flush=in_flush,
    )


def plan(item: str, seed: int) -> ScrPlan | MboxPlan:
    """The parameter plan of ``item`` for ``seed``."""
    if item == T_SCR:
        return _scr_plan(seed)
    if item == T_MBOX_KM:
        return _mbox_plan(seed)
    raise KeyError(f"{item} has no KM ROM parameter block")


def block_words(item: str, seed: int) -> list[int]:
    """The parameter block of ``item`` for ``seed``, header and check word included."""
    p = plan(item, seed)
    block_id = BLOCK_SCR if item == T_SCR else BLOCK_MBOX_KM
    payload = [w & WORD_MASK for w in p.payload()]
    words = [PARAM_MAGIC, (PARAM_VERSION << 16) | block_id, len(payload)] + payload
    check = 0
    for w in words:
        check ^= w
    words.append(check)
    if len(words) > PARAM_MAX_WORDS:
        raise RuntimeError(f"{item}: block of {len(words)} words exceeds {PARAM_MAX_WORDS}")
    return words


def _template_last_word(lines: list[str]) -> int:
    """Highest ROM word index that a parhex template writes (-1 when empty)."""
    addr = 0
    last = -1
    for raw in lines:
        tok = raw.strip()
        if not tok or tok.startswith("//"):
            continue
        if tok.startswith("@"):
            addr = int(tok[1:], 16)
            continue
        last = max(last, addr)
        addr += 1
    return last


def staged_text(template: Path, item: str, seed: int) -> str:
    """The staged image: the template, then the block at ``PARAM_BASE_WORD``.

    Each block line is 9 hex digits, ``{parity[3:0]}{word[31:0]}``, in the format
    of ``tests/km_fw/gen_parhex.py``. A template that reaches the block raises.
    """
    text = template.read_text(encoding="ascii")
    lines = text.splitlines()
    last = _template_last_word(lines)
    if last >= PARAM_BASE_WORD:
        raise ValueError(
            f"{template}: image reaches ROM word {last:#x}, at or above the parameter "
            f"block at {PARAM_BASE_WORD:#x}"
        )
    out = list(lines) + [f"@{PARAM_BASE_WORD:08X}"]
    out += [f"{word_parity(w):X}{w:08X}" for w in block_words(item, seed)]
    return "\n".join(out) + "\n"


def identity(text: str) -> str:
    """sha256 of a staged image text."""
    return hashlib.sha256(text.encode("ascii")).hexdigest()
