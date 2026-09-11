# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-derived set-only shadow OR-merge policy.

Every ``periphs.adoc`` fuse-field row except ``LC_STATE`` is walked.
Set-only rows come from ``spec_set_only_walk``; SW-writable ``true``
rows come from ``spec_writable_shadow_walk``. ``LOCK`` is the
unassigned ``LOCKS_SPARE`` bits so assigned lock slots stay clear.
The lifecycle nibble stays with the LC W1S leaves.

A shadow write OR-merges with the stored word. ``SIP_DIS`` and
``SYS_DIS`` stay on their function-group word so the walk does not
OR debug bits into ``FEAT_CTRL``.

``dv_sim_prestage.py`` loads this module to stage the t=0 hex; the test
builds the same ``SepEfuseSetOnlyCfg(seed)`` as its golden. Do not switch
the stream to ``random.Random`` — that would desynchronize the two
processes.
"""

from __future__ import annotations

from sep_efuse_field_map import spec_set_only_walk, spec_writable_shadow_walk
from sep_efuse_image import SepEfuseImage
from sep_seeded_rng import SepSeededRng

# From the specification table, plus the DIS function-group pin so the walk
# does not OR debug bits into FEAT_CTRL. Word 0 carries sep_debug, chiplet_dbg,
# the fuse-dbg bits and sip_debug.
SET_ONLY_FIELDS: tuple[tuple[str, int, "int | None"], ...] = spec_set_only_walk()
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
        assert all(f.name != "LC_STATE" for f in self.fields)
        assert any(f.name == "LOCKS_SPARE" for f in self.fields)
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
        fixed = {f.name: f.field_int for f in self.fields}
        for field in self.writable:
            fixed[field.name] = 0
        return fixed

    def summary(self) -> str:
        parts = [
            f"{f.name}[w{f.word_idx}]=sensed=0x{f.sensed:x}/set=0x{f.set_bits:x}"
            for f in self.fields
        ]
        wr = [f"{w.name}=0x{w.pattern:x}" for w in self.writable]
        return (
            f"seed={self.seed} cells={len(self.fields)} "
            f"{' '.join(parts)} writable={' '.join(wr)}"
        )


def _selftest() -> None:
    from sep_efuse_field_map import spec_fields, spec_walked_rows

    assert [n for n, _, _ in SET_ONLY_FIELDS] == [
        "LOCKS_SPARE",
        "SIP_DIS",
        "SYS_DIS",
        "CHIPLET_PUBK_REVOKE",
        "BL1_VERSION",
        "BL2_VERSION",
        "REQUIRED_ALGS",
    ]
    # Both specification disable vectors must be walked.
    assert {"SIP_DIS", "SYS_DIS"} <= {n for n, _, _ in SET_ONLY_FIELDS}
    assert len(WRITABLE_FIELDS) == 33
    assert "REQUIRED_SIGNERS" in {n for n, _ in WRITABLE_FIELDS}
    assert spec_walked_rows() == {f.spec_name for f in spec_fields()} - {"LC_STATE"}

    cfg = SepEfuseSetOnlyCfg(1)
    for f in cfg.fields:
        # sensed and set_bits must be disjoint or the OR-merge check cannot
        # distinguish a set from a value that was already there.
        assert (f.sensed & f.set_bits) == 0, f"{f.name}: sensed and set overlap"
        assert f.sensed and f.set_bits, f"{f.name}: empty mask"
        assert (f.sensed | f.set_bits) & ~f.used_mask == 0, (
            f"{f.name}: pattern outside the spec-stated used bits"
        )

    # The DIS vectors must stay clear of every bit that lands in FEAT_CTRL:
    # sep_debug (0), chiplet_dbg (1), the fuse-dbg bits (2, 3) and sip_debug
    # (24) all live in word 0.
    for f in cfg.fields:
        if f.name in ("SIP_DIS", "SYS_DIS"):
            assert f.word_idx == 1, f"{f.name} must stay off the debug-group word"
        if f.name == "LOCKS_SPARE":
            assert f.word_idx == 0
            assert f.used_mask == 0xFFFF_0000

    # Two constructions from one seed agree -- the prestage process and the test
    # build this independently and must land on the same image.
    again = SepEfuseSetOnlyCfg(1)
    assert again.image_fixed() == cfg.image_fixed()
    assert [(w.name, w.pattern) for w in again.writable] == [
        (w.name, w.pattern) for w in cfg.writable
    ]
    for field in cfg.writable:
        assert field.pattern
        assert field.pattern == (field.pattern & field.used_mask)


_selftest()
