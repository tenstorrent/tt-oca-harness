# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-derived set-only shadow OR-merge policy.

Every ``periphs.adoc`` fuse-field row except ``LC_STATE`` is walked.
Set-only rows come from ``spec_set_only_walk``; ``LOCK`` comes from
``spec_lock_walk`` (both ``LOCKS`` words and ``LOCKS_SPARE``) after the
other rows; SW-writable ``true`` rows come from
``spec_writable_shadow_walk``. Assigned lock slots stay 0 at sense so
they do not write-lock a row this sweep still writes. The lifecycle
nibble stays with the LC W1S leaves.

A shadow write OR-merges with the stored word. ``SIP_DIS`` and
``SYS_DIS`` stay on their function-group word so the walk does not
OR debug bits into ``FEAT_CTRL``.

``dv_sim_prestage.py`` loads this module to stage the t=0 hex; the test
builds the same ``SepEfuseSetOnlyCfg(seed)`` as its golden. Do not switch
the stream to ``random.Random`` — that would desynchronize the two
processes.
"""

from __future__ import annotations

from sep_efuse_field_map import (
    spec_lock_walk,
    spec_set_only_walk,
    spec_writable_shadow_walk,
)
from sep_efuse_image import SepEfuseImage
from sep_seeded_rng import SepSeededRng

# From the specification table, plus the DIS function-group pin so the walk
# does not OR debug bits into FEAT_CTRL. Word 0 carries sep_debug, chiplet_dbg,
# the fuse-dbg bits and sip_debug. LOCK is the late walk of both RDL windows.
SET_ONLY_FIELDS: tuple[tuple[str, int, "int | None"], ...] = spec_set_only_walk()
LOCK_FIELDS: tuple[tuple[str, int, int, int, int], ...] = spec_lock_walk()
WRITABLE_FIELDS: tuple[tuple[str, int], ...] = spec_writable_shadow_walk()
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1


class SepEfuseSetOnlyField:
    """One walked set-only word: sensed ones, then a disjoint set-bit."""

    def __init__(
        self,
        name: str,
        word_idx: int,
        used_mask: int,
        sensed: int,
        set_bits: int,
    ) -> None:
        self.name = name
        self.word_idx = word_idx
        self.used_mask = used_mask
        self.sensed = sensed
        self.set_bits = set_bits

    @property
    def after_set(self) -> int:
        return (self.sensed | self.set_bits) & WORD_MASK

    @property
    def field_int(self) -> int:
        return (self.sensed & WORD_MASK) << (WORD_BITS * self.word_idx)

    def drive_word(self, used_payload: int) -> int:
        return (used_payload & self.used_mask) & WORD_MASK


def _used_bits(mask: int) -> list[int]:
    return [i for i in range(WORD_BITS) if mask & (1 << i)]


def _draw_masks(rng: SepSeededRng, used_mask: int) -> tuple[int, int]:
    """Nonempty disjoint sensed / set masks inside ``used_mask``."""
    bits = _used_bits(used_mask)
    if len(bits) < 2:
        raise ValueError(f"set-only used_mask 0x{used_mask:x} has fewer than 2 bits")
    set_bit = bits.pop(rng.randrange(len(bits)))
    sensed_bit = bits.pop(rng.randrange(len(bits)))
    sensed = 1 << sensed_bit
    for bit in bits:
        if rng.getrandbits(1):
            sensed |= 1 << bit
    return sensed, (1 << set_bit)


def _draw_ones(rng: SepSeededRng, mask: int) -> int:
    """Nonempty subset of ``mask``, or 0 when ``mask`` is 0."""
    bits = _used_bits(mask)
    if not bits:
        return 0
    chosen = bits.pop(rng.randrange(len(bits)))
    value = 1 << chosen
    for bit in bits:
        if rng.getrandbits(1):
            value |= 1 << bit
    return value


def _draw_one_bit(rng: SepSeededRng, mask: int) -> int:
    bits = _used_bits(mask)
    if not bits:
        raise ValueError(f"set-only set_mask 0x{mask:x} has no bits")
    return 1 << bits[rng.randrange(len(bits))]


class SepEfuseWritableField:
    """One walked SW-writable word: sensed 0, then a nonempty overwrite."""

    def __init__(self, name: str, word_idx: int, used_mask: int, pattern: int) -> None:
        self.name = name
        self.word_idx = word_idx
        self.used_mask = used_mask
        self.pattern = pattern


class SepEfuseSetOnlyCfg:
    """RANDCFG SSOT: walk every legal set-only field; patterns from the seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.fields: tuple[SepEfuseSetOnlyField, ...] = tuple(
            self._draw_field(rng, name, used, pin) for name, used, pin in SET_ONLY_FIELDS
        )
        self.writable: tuple[SepEfuseWritableField, ...] = tuple(
            self._draw_writable(rng, name, used) for name, used in WRITABLE_FIELDS
        )
        self.lock_fields: tuple[SepEfuseSetOnlyField, ...] = tuple(
            self._draw_lock_field(rng, name, used, word, sensed_m, set_m)
            for name, used, word, sensed_m, set_m in LOCK_FIELDS
        )
        assert all(f.name != "LC_STATE" for f in self.fields)
        assert not any(f.name in ("LOCKS", "LOCKS_SPARE") for f in self.fields)
        assert {f.name for f in self.lock_fields} == {"LOCKS", "LOCKS_SPARE"}
        assert any(f.name == "LOCKS" and f.word_idx == 0 for f in self.lock_fields)
        assert any(f.name == "LOCKS" and f.word_idx == 1 for f in self.lock_fields)
        assert any(w.name == "REQUIRED_SIGNERS" for w in self.writable)

    @staticmethod
    def _draw_field(
        rng: SepSeededRng,
        name: str,
        used_mask: int,
        pinned_word: int | None = None,
    ) -> SepEfuseSetOnlyField:
        fld = SepEfuseImage.field(name)
        # Draw either way so the seed stream does not shift when a field gains
        # or loses a pin -- the prestage process and the test must agree.
        drawn_word = rng.randrange(fld.n_words)
        word_idx = drawn_word if pinned_word is None else pinned_word
        assert 0 <= word_idx < fld.n_words, (
            f"{name} pinned to word {word_idx}, which is outside its {fld.n_words}-word extent"
        )
        sensed, set_bits = _draw_masks(rng, used_mask)
        assert sensed and set_bits
        assert (sensed & set_bits) == 0
        assert (sensed | set_bits) == ((sensed | set_bits) & used_mask)
        return SepEfuseSetOnlyField(
            name=name,
            word_idx=word_idx,
            used_mask=used_mask,
            sensed=sensed,
            set_bits=set_bits,
        )

    @staticmethod
    def _draw_lock_field(
        rng: SepSeededRng,
        name: str,
        used_mask: int,
        word_idx: int,
        sensed_mask: int,
        set_mask: int,
    ) -> SepEfuseSetOnlyField:
        fld = SepEfuseImage.field(name)
        assert 0 <= word_idx < fld.n_words, (
            f"{name} lock word {word_idx} is outside its {fld.n_words}-word extent"
        )
        sensed = _draw_ones(rng, sensed_mask)
        set_bits = _draw_one_bit(rng, set_mask)
        assert set_bits
        assert (sensed & set_bits) == 0
        assert (sensed | set_bits) == ((sensed | set_bits) & used_mask)
        return SepEfuseSetOnlyField(
            name=name,
            word_idx=word_idx,
            used_mask=used_mask,
            sensed=sensed,
            set_bits=set_bits,
        )

    @staticmethod
    def _draw_writable(rng: SepSeededRng, name: str, used_mask: int) -> SepEfuseWritableField:
        fld = SepEfuseImage.field(name)
        word_idx = rng.randrange(fld.n_words)
        bits = _used_bits(used_mask)
        if not bits:
            raise ValueError(f"{name} used_mask 0x{used_mask:x} has no bits")
        # Draw a word, then force at least one used bit so write-0 is a real clear.
        pattern = rng.getrandbits(WORD_BITS) & used_mask
        if pattern == 0:
            pattern = 1 << bits[0]
        return SepEfuseWritableField(name, word_idx, used_mask, pattern)

    def image_fixed(self) -> dict[str, int]:
        """``select_efuse_image(fixed=...)`` pins that match this config."""
        fixed: dict[str, int] = {}
        for field in (*self.fields, *self.lock_fields):
            fixed[field.name] = fixed.get(field.name, 0) | field.field_int
        for field in self.writable:
            fixed[field.name] = 0
        return fixed

    def summary(self) -> str:
        parts = [
            f"{f.name}[w{f.word_idx}]=sensed=0x{f.sensed:x}/set=0x{f.set_bits:x}"
            for f in (*self.fields, *self.lock_fields)
        ]
        wr = [f"{w.name}=0x{w.pattern:x}" for w in self.writable]
        return (
            f"seed={self.seed} cells={len(self.fields)}+{len(self.lock_fields)}lock "
            f"{' '.join(parts)} writable={' '.join(wr)}"
        )


def _selftest() -> None:
    from sep_efuse_field_map import spec_fields, spec_walked_rows

    assert [n for n, _, _ in SET_ONLY_FIELDS] == [
        "SIP_DIS",
        "SYS_DIS",
        "CHIPLET_PUBK_REVOKE",
        "BL1_VERSION",
        "BL2_VERSION",
        "REQUIRED_ALGS",
    ]
    assert [n for n, *_ in LOCK_FIELDS] == ["LOCKS", "LOCKS", "LOCKS_SPARE"]
    # Both specification disable vectors must be walked.
    assert {"SIP_DIS", "SYS_DIS"} <= {n for n, _, _ in SET_ONLY_FIELDS}
    assert len(WRITABLE_FIELDS) == 34
    assert "REQUIRED_SIGNERS" in {n for n, _ in WRITABLE_FIELDS}
    assert spec_walked_rows() == {f.spec_name for f in spec_fields()} - {"LC_STATE"}

    cfg = SepEfuseSetOnlyCfg(1)
    for f in (*cfg.fields, *cfg.lock_fields):
        # sensed and set_bits must be disjoint or the OR-merge check cannot
        # distinguish a set from a value that was already there.
        assert (f.sensed & f.set_bits) == 0, f"{f.name}: sensed and set overlap"
        assert f.set_bits, f"{f.name}: empty set mask"
        assert (f.sensed | f.set_bits) & ~f.used_mask == 0, (
            f"{f.name}: pattern outside the spec-stated used bits"
        )
        if f.name not in ("LOCKS",):
            assert f.sensed, f"{f.name}: empty sensed mask"

    # The DIS vectors must stay clear of every bit that lands in FEAT_CTRL:
    # sep_debug (0), chiplet_dbg (1), the fuse-dbg bits (2, 3) and sip_debug
    # (24) all live in word 0.
    for f in cfg.fields:
        if f.name in ("SIP_DIS", "SYS_DIS"):
            assert f.word_idx == 1, f"{f.name} must stay off the debug-group word"

    locks = [f for f in cfg.lock_fields if f.name == "LOCKS"]
    assert {f.word_idx for f in locks} == {0, 1}
    assert all(f.sensed == 0 for f in locks)
    spare = next(f for f in cfg.lock_fields if f.name == "LOCKS_SPARE")
    assert spare.word_idx == 0
    _spare_sensed, _spare_set = LOCK_FIELDS[-1][3], LOCK_FIELDS[-1][4]
    assert spare.sensed and spare.sensed == (spare.sensed & _spare_sensed)
    assert spare.set_bits and spare.set_bits == (spare.set_bits & _spare_set)
    pins = cfg.image_fixed()
    assert pins["LOCKS"] == 0
    assert pins["LOCKS_SPARE"] == spare.field_int

    # Two constructions from one seed agree -- the prestage process and the test
    # build this independently and must land on the same image.
    again = SepEfuseSetOnlyCfg(1)
    assert again.image_fixed() == cfg.image_fixed()
    assert [(w.name, w.pattern) for w in again.writable] == [
        (w.name, w.pattern) for w in cfg.writable
    ]
    assert [(f.name, f.word_idx, f.sensed, f.set_bits) for f in again.lock_fields] == [
        (f.name, f.word_idx, f.sensed, f.set_bits) for f in cfg.lock_fields
    ]
    for field in cfg.writable:
        assert field.pattern
        assert field.pattern == (field.pattern & field.used_mask)


_selftest()
