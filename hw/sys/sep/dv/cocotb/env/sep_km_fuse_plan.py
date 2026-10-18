# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded fuse-image plans of the Key Manager OTP and eFuse-window tests.

``sep_km_crossbar_efuse_window_rand_test`` and ``sep_km_otp_interface_rand_test``
sense a fuse image that depends on the seed of the leaf. ``plan(item, seed)``
draws the whole leaf plan from ``SepSeededRng(seed)`` in a fixed order and
returns it with the 256 image words. ``dv_sim_prestage.py`` writes those words
to ``out/sep_efuse.hex`` before the simulator starts, and the test calls the
same ``plan(item, seed)`` at runtime for its golden, so the staged image and
the golden are one function of the seed.

No cocotb import: the pre-sim staging hook loads this module by path.

The stream is not a CSPRNG. Every drawn word is a labelled test vector that
lives only in the simulation, and no per-seed value is evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sep_efuse_image import (
    LC_PROD,
    LC_TEST_DEV,
    NUM_FUSE_WORDS,
    WORD_BITS,
    WORD_MASK,
    SepEfuseImage,
)
from sep_reg_meta import RegBlock
from sep_seeded_rng import SepSeededRng

T_XBAR_EFUSE = "sep_km_crossbar_efuse_window_rand_test"
T_OTP_IFACE = "sep_km_otp_interface_rand_test"
TESTS = (T_XBAR_EFUSE, T_OTP_IFACE)

_EFUSE_MAP = RegBlock("SEP_EFUSE_MAP")

# Fields that a plan never draws: the lock vectors, the life-cycle word and the
# two disable vectors (sep_efuse_map.adoc; the VPLAN rule that a draw never sets
# a disable-vector bit).
FIXED_FIELDS = ("LOCKS", "LOCKS_SPARE", "LC_STATE", "SIP_DIS", "SYS_DIS")
SPARE_FIELDS = tuple(f"SPARE{i}" for i in range(9))
# Lockable fields of the eFuse-window plan: every field with a lock slot, less
# the fixed fields and the spares, which keep both lock bits clear.
_LOCKABLE = tuple(
    f.name
    for f in SepEfuseImage.fields
    if f.name not in FIXED_FIELDS and f.name not in SPARE_FIELDS and f.kind == "data"
)
# The seven dual-rail 256-bit fields of the KM OTP input (architecture.adoc, OTP
# Inputs and Readout), in OTP_READ_LOCK bit order 2 to 8.
OTP_DUAL_RAIL_FIELDS = (
    "CHIPLET_UID",
    "SIP_UID",
    "SYS_UID",
    "CLASS_KEY",
    "SEP_CHIPLET_ID",
    "SEP_SIP_ID",
    "SEP_SYS_ID",
)
# The two fields that the OTP leaf writes through the shadow registers with one
# added bit; the plan stages them at 0, so every used bit is a 0 bit.
OTP_SHADOW_WRITE_FIELDS = ("REQUIRED_ALGS", "REQUIRED_SIGNERS")
# OTP_READ_LOCK holds nine field bits.
OTP_LOCK_FIELDS = 9
OTP_LOCK_ALL = (1 << OTP_LOCK_FIELDS) - 1

# A draw that cannot find a fresh word in this many tries is a generator bug:
# each try fails with probability below 2^-20 for the word counts here.
_DRAW_TRIES = 16


def _lsb(field_name: str, kind: str) -> tuple[str, int]:
    """(lock register, bit) of the ``kind`` lock ("read" or "write") of a field."""
    name = f"{field_name.lower()}_{kind}_lock"
    for reg in ("LOCKS", "LOCKS_SPARE"):
        try:
            return reg, int(_EFUSE_MAP.field_lsb(reg, name))
        except (KeyError, ValueError, AttributeError):
            continue
    raise KeyError(f"no {kind} lock bit for {field_name}")


def read_lock_bit(field_name: str) -> tuple[str, int]:
    return _lsb(field_name, "read")


def write_lock_bit(field_name: str) -> tuple[str, int]:
    return _lsb(field_name, "write")


def field_word(name: str) -> int:
    word: int = SepEfuseImage.field(name).word
    return word


def field_n_words(name: str) -> int:
    n_words: int = SepEfuseImage.field(name).n_words
    return n_words


def bit_address(name: str, word: int, bit: int) -> int:
    """eFuse bit address of ``bit`` of word ``word`` of field ``name``."""
    addr: int = (field_word(name) + word) * WORD_BITS + bit
    return addr


@dataclass(frozen=True)
class FuseTarget:
    """One program target: a bit that is 0 in the staged word."""

    field: str
    word: int
    bit: int

    @property
    def address(self) -> int:
        return bit_address(self.field, self.word, self.bit)


@dataclass
class KmFusePlan:
    """The leaf plan: the staged image words and the drawn dimensions."""

    item: str
    seed: int
    lc_raw: int
    words: list[int]
    read_locked: str = ""
    write_locked: str = ""
    targets: dict[str, FuseTarget] = field(default_factory=dict)
    lock_mask_a: int = 0
    otp_fields: dict[str, int] = field(default_factory=dict)

    def image(self) -> SepEfuseImage:
        img = SepEfuseImage()
        img.words = list(self.words)
        return img

    def identity(self) -> str:
        """sha256 of the staged image text (the bytes ``write_hex`` writes)."""
        text = "".join(f"{w & WORD_MASK:08x}\n" for w in self.words)
        return hashlib.sha256(text.encode("ascii")).hexdigest()

    def summary(self) -> str:
        parts = [f"item={self.item}", f"seed={self.seed}", f"lc_raw={self.lc_raw:#x}"]
        if self.read_locked:
            parts.append(f"read_locked={self.read_locked}")
        if self.write_locked:
            parts.append(f"write_locked={self.write_locked}")
        for key, tgt in sorted(self.targets.items()):
            parts.append(f"{key}={tgt.field}[{tgt.word}].{tgt.bit}")
        if self.lock_mask_a:
            parts.append(f"lock_mask_a={self.lock_mask_a:#05x}")
        parts.append(f"image_sha256={self.identity()}")
        return " ".join(parts)


def _fresh_word(rng: SepSeededRng, taken: set[int]) -> int:
    """A word that is not 0, not all ones and not in ``taken``.

    A word with no 0 bit has no program target, and a word of all ones has a
    zero complement, so both are excluded.
    """
    for _ in range(_DRAW_TRIES):
        word: int = rng.getrandbits(WORD_BITS)
        if word not in (0, WORD_MASK) and word not in taken:
            taken.add(word)
            return word
    raise RuntimeError(f"no fresh fuse word in {_DRAW_TRIES} draws")


def _zero_bit(rng: SepSeededRng, word: int) -> int:
    zeros = [b for b in range(WORD_BITS) if not (word >> b) & 1]
    return int(rng.choice(zeros))


def _set_lock(words: list[int], lock: tuple[str, int]) -> None:
    reg, bit = lock
    base = field_word(reg)
    words[base + bit // WORD_BITS] |= 1 << (bit % WORD_BITS)


def _xbar_efuse_plan(seed: int) -> KmFusePlan:
    """The eFuse-window plan (sep_km_crossbar_efuse_window_rand_test, Randomization).

    Every shadow word outside the fixed fields is drawn non-zero and pairwise
    different. LC_STATE is TEST_DEV, SIP_DIS and SYS_DIS are 0. One drawn
    lockable field has its read lock and a different one its write lock in
    LOCKS; LOCKS_SPARE stays 0. Two spare fields carry the program targets of
    the two paths, the write-locked field the denied target, and two more
    spare fields the secure-test targets. Each target bit is 0 in the staged
    word.
    """
    rng = SepSeededRng(seed)
    words = [0] * NUM_FUSE_WORDS
    fixed_words = {field_word(n) + i for n in FIXED_FIELDS for i in range(field_n_words(n))}
    taken: set[int] = set()
    for idx in range(NUM_FUSE_WORDS):
        if idx not in fixed_words:
            words[idx] = _fresh_word(rng, taken)
    read_locked, write_locked = rng.sample(_LOCKABLE, 2)
    _set_lock(words, read_lock_bit(read_locked))
    _set_lock(words, write_lock_bit(write_locked))
    spares = rng.sample(SPARE_FIELDS, 4)
    targets: dict[str, FuseTarget] = {}
    for key, name in (
        ("km_spare", spares[0]),
        ("host_spare", spares[1]),
        ("denied", write_locked),
        ("tm_km_spare", spares[2]),
        ("tm_host_spare", spares[3]),
    ):
        word = rng.randrange(field_n_words(name))
        staged = words[field_word(name) + word]
        targets[key] = FuseTarget(name, word, _zero_bit(rng, staged))
    img = SepEfuseImage()
    img.words = words
    img.set_lc_state(LC_TEST_DEV)
    return KmFusePlan(
        item=T_XBAR_EFUSE,
        seed=seed,
        lc_raw=LC_TEST_DEV,
        words=list(img.words),
        read_locked=read_locked,
        write_locked=write_locked,
        targets=targets,
    )


def _otp_iface_plan(seed: int) -> KmFusePlan:
    """The OTP-interface plan (sep_km_otp_interface_rand_test, Randomization, class one).

    The seven dual-rail fields hold words that are neither 0 nor all ones, so
    every value word and every complement word has a set bit, and no word
    repeats across the fields. The life-cycle state is TEST_DEV or PROD with
    equal weight. The lock mask A has 1 to 8 of the 9 field bits. LOCKS,
    LOCKS_SPARE, SIP_DIS, SYS_DIS and the two shadow-write fields are 0; every
    other word is drawn non-zero.
    """
    rng = SepSeededRng(seed)
    lc_raw = LC_TEST_DEV if rng.getrandbits(1) == 0 else LC_PROD
    a = 0
    while not 1 <= bin(a).count("1") <= OTP_LOCK_FIELDS - 1:
        a = rng.getrandbits(OTP_LOCK_FIELDS)
    words = [0] * NUM_FUSE_WORDS
    zero_fields = FIXED_FIELDS + OTP_SHADOW_WRITE_FIELDS
    zero_words = {field_word(n) + i for n in zero_fields for i in range(field_n_words(n))}
    taken: set[int] = set()
    otp_fields: dict[str, int] = {}
    for name in OTP_DUAL_RAIL_FIELDS:
        value = 0
        for i in range(field_n_words(name)):
            w = _fresh_word(rng, taken)
            words[field_word(name) + i] = w
            value |= w << (WORD_BITS * i)
        otp_fields[name] = value
    for idx in range(NUM_FUSE_WORDS):
        if idx not in zero_words and words[idx] == 0:
            words[idx] = _fresh_word(rng, taken)
    img = SepEfuseImage()
    img.words = words
    img.set_lc_state(lc_raw)
    return KmFusePlan(
        item=T_OTP_IFACE,
        seed=seed,
        lc_raw=lc_raw,
        words=list(img.words),
        lock_mask_a=a,
        otp_fields=otp_fields,
    )


def plan(item: str, seed: int) -> KmFusePlan:
    """The leaf plan of ``item`` for ``seed``."""
    if item == T_XBAR_EFUSE:
        return _xbar_efuse_plan(seed)
    if item == T_OTP_IFACE:
        return _otp_iface_plan(seed)
    raise KeyError(f"{item} has no Key Manager fuse plan")


def image_words(item: str, seed: int) -> list[int]:
    """The 256 t=0 image words of ``item`` for ``seed``."""
    return plan(item, seed).words
