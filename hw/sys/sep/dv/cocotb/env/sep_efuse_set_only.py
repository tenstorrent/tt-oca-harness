# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-derived set-only shadow OR-merge policy.

Legal set-only fields are metal-fixed ``WRITE_SET_ONLY`` in
``sep_efuse_pkg::EfuseFieldMap``: ``BL1_VERSION``, ``BL2_VERSION``,
``CHIPLET_PUBK_REVOKE``, ``REQUIRED_SIGNERS``, ``REQUIRED_ALGS``. This
walk is that metal map, not the ``periphs.adoc`` SW-writable column:
``REQUIRED_SIGNERS`` is ``true`` there (firmware may update the shadow
per manifest; fuse monotonicity is the burn). A shadow write OR-merges
with the stored word (``hw/ip/efuse/rtl/efuse_shadow_regs.sv``).
``LC_STATE`` is not a member of this walk.

``dv_sim_prestage.py`` loads this module to stage the t=0 hex; the test
builds the same ``SepEfuseSetOnlyCfg(seed)`` as its golden. Do not switch
the stream to ``random.Random`` — that would desynchronize the two
processes.
"""

from __future__ import annotations

from sep_efuse_image import SepEfuseImage
from sep_seeded_rng import SepSeededRng

# Spec-stated used-bit masks (periphs.adoc). Multi-word version fields
# apply the mask to the seed-selected word.
SET_ONLY_FIELDS: tuple[tuple[str, int], ...] = (
    ("BL1_VERSION", 0xFFFF_FFFF),
    ("BL2_VERSION", 0xFFFF_FFFF),
    ("CHIPLET_PUBK_REVOKE", 0xFFFF_FFFF),
    ("REQUIRED_SIGNERS", 0x3),
    ("REQUIRED_ALGS", 0xFFF),
)
CONTRAST_FIELD = "SPARE0"
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


class SepEfuseSetOnlyCfg:
    """RANDCFG SSOT: walk every legal set-only field; patterns from the seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.fields: tuple[SepEfuseSetOnlyField, ...] = tuple(
            self._draw_field(rng, name, used) for name, used in SET_ONLY_FIELDS
        )
        self.spare_pattern = rng.getrandbits(WORD_BITS) | 1
        assert all(f.name != "LC_STATE" for f in self.fields)

    @staticmethod
    def _draw_field(
        rng: SepSeededRng, name: str, used_mask: int,
    ) -> SepEfuseSetOnlyField:
        fld = SepEfuseImage.field(name)
        word_idx = rng.randrange(fld.n_words)
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

    def image_fixed(self) -> dict[str, int]:
        """``select_efuse_image(fixed=...)`` pins that match this config."""
        fixed = {f.name: f.field_int for f in self.fields}
        fixed[CONTRAST_FIELD] = 0
        return fixed

    def summary(self) -> str:
        parts = [
            f"{f.name}[w{f.word_idx}]=sensed=0x{f.sensed:x}/set=0x{f.set_bits:x}"
            for f in self.fields
        ]
        return (
            f"seed={self.seed} cells={len(self.fields)} "
            f"{' '.join(parts)} {CONTRAST_FIELD}=0x{self.spare_pattern:08x}"
        )


def _selftest() -> None:
    assert [n for n, _ in SET_ONLY_FIELDS] == [
        "BL1_VERSION",
        "BL2_VERSION",
        "CHIPLET_PUBK_REVOKE",
        "REQUIRED_SIGNERS",
        "REQUIRED_ALGS",
    ]
    assert CONTRAST_FIELD != "LC_STATE"
    cfg = SepEfuseSetOnlyCfg(1)
    assert len(cfg.fields) == len(SET_ONLY_FIELDS)
    assert {f.name for f in cfg.fields} == {n for n, _ in SET_ONLY_FIELDS}
    assert "LC_STATE" not in cfg.image_fixed()
    for f in cfg.fields:
        assert f.sensed
        assert f.set_bits
        assert (f.sensed & f.set_bits) == 0
        assert (f.sensed | 0) == f.sensed
        assert f.after_set == (f.sensed | f.set_bits)
        assert (f.after_set | 0) == f.after_set
        fld = SepEfuseImage.field(f.name)
        assert 0 <= f.word_idx < fld.n_words
        assert cfg.image_fixed()[f.name] == f.field_int
    again = SepEfuseSetOnlyCfg(1)
    assert again.image_fixed() == cfg.image_fixed()
    assert again.spare_pattern == cfg.spare_pattern
    assert cfg.spare_pattern != 0


_selftest()
