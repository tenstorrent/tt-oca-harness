# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-derived set-only shadow OR-merge policy.

Legal set-only fields are metal-fixed ``WRITE_SET_ONLY`` in
``sep_efuse_pkg::EfuseFieldMap``. This walk is that metal map, not the
``periphs.adoc`` SW-writable column: ``REQUIRED_SIGNERS`` is ``true``
there (firmware may update the shadow per manifest; fuse monotonicity is
the burn). A shadow write OR-merges with the stored word
(``hw/ip/efuse/rtl/efuse_shadow_regs.sv``).

Two storage arms, not one. ``efuse_shadow_regs.sv`` forks the OR-merge on
whether the word is in ``Class1ShadowRanges``: Class-1 words merge into
``shadow_efuse_values_n0_scan`` via ``class1_shadow_storage_idx``,
everything else into ``shadow_efuse_values`` via
``normal_shadow_storage_idx``. Walking only non-Class-1 fields leaves the
Class-1 arm unexercised, so ``SIP_DIS`` and ``SYS_DIS`` are members here:
they are ``WRITE_SET_ONLY`` with a ``SECURE_TM_LOCK`` that drops at
``secure_tm=0``, and they are Class-1.

``LC_STATE`` and ``LOCKS`` are set-only and Class-1 too, and are still not
members: ``LC_STATE`` has its own lifecycle walk, and burning ``LOCKS``
would write-lock the fields this test needs to keep writing.

``dv_sim_prestage.py`` loads this module to stage the t=0 hex; the test
builds the same ``SepEfuseSetOnlyCfg(seed)`` as its golden. Do not switch
the stream to ``random.Random`` — that would desynchronize the two
processes.
"""

from __future__ import annotations

from sep_efuse_image import SepEfuseImage
from sep_seeded_rng import SepSeededRng

# Spec-stated used-bit masks (periphs.adoc). Multi-word version fields
# apply the mask to the seed-selected word, unless the entry pins one.
#
# The DIS vectors are pinned to word 1 with a mask over the function group
# only. Word 0 carries DBG_1 and the low half of DBG_2 -- sep_debug at bit 0,
# chiplet_dbg at bit 1, sep_fuse_dbg at bit 2, smc_fuse_dbg at bit 3,
# sip_debug at bit 24 -- and setting any of those ORs those bits into
# FEAT_CTRL. This test drives the CPU-LSU master, which has no inbound
# filter; the pin still keeps the walk from changing FEAT_CTRL mid-run.
# The function group is reserved or tied off for a no_cpu run, so it is
# writable without disturbing fabric access.
#   name -> (used_mask, pinned word index or None)
SET_ONLY_FIELDS: tuple[tuple[str, int, "int | None"], ...] = (
    ("BL1_VERSION", 0xFFFF_FFFF, None),
    ("BL2_VERSION", 0xFFFF_FFFF, None),
    ("CHIPLET_PUBK_REVOKE", 0xFFFF_FFFF, None),
    ("REQUIRED_SIGNERS", 0x3, None),
    ("REQUIRED_ALGS", 0xFFF, None),
    # Class-1 storage arm. Function group = LC_DISABLE bits [63:48] = word 1
    # bits [31:16].
    ("SIP_DIS", 0xFFFF_0000, 1),
    ("SYS_DIS", 0xFFFF_0000, 1),
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
            self._draw_field(rng, name, used, pin) for name, used, pin in SET_ONLY_FIELDS
        )
        self.spare_pattern = rng.getrandbits(WORD_BITS) | 1
        assert all(f.name != "LC_STATE" for f in self.fields)

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
    # The literal list is the point: it is written here, not comprehended from
    # SET_ONLY_FIELDS, so adding or dropping a member fails until someone
    # decides that was intended. Nine fields carry WRITE_SET_ONLY in
    # sep_efuse_pkg::EfuseFieldMap; the two absent here are LC_STATE (its own
    # lifecycle walk) and LOCKS (burning it would lock the fields under test).
    assert [n for n, _, _ in SET_ONLY_FIELDS] == [
        "BL1_VERSION",
        "BL2_VERSION",
        "CHIPLET_PUBK_REVOKE",
        "REQUIRED_SIGNERS",
        "REQUIRED_ALGS",
        "SIP_DIS",
        "SYS_DIS",
    ]
    # At least one Class-1 member, or the Class-1 OR-merge arm in
    # efuse_shadow_regs.sv goes unexercised and nothing here would say so.
    assert {"SIP_DIS", "SYS_DIS"} <= {n for n, _, _ in SET_ONLY_FIELDS}

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

    # Two constructions from one seed agree -- the prestage process and the test
    # build this independently and must land on the same image.
    again = SepEfuseSetOnlyCfg(1)
    assert again.image_fixed() == cfg.image_fixed()
    assert again.spare_pattern == cfg.spare_pattern


_selftest()
