# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A diverse eFuse image for the shadow fan-out coverage leaf.

``shadow_regs_o`` fans out from ``efuse_shadow_regs`` to ``sep_efuse_wrapper``,
``sep_lifecycle_ctrl`` and ``efuse_interface_controller``. Those consumers
execute every line while most of the 256 x 32 bits they carry stay at their
reset value, because every test in the suite senses a near-blank image: a
bit that is zero in OTP is zero in the shadow and never moves.

This config pins the freely-writable fuse words to an alternating
``0x5555_5555`` / ``0xAAAA_AAAA`` pattern, so half of every word is one after
sense and the two halves swap between neighbouring words. Sensing it once
drives the rising edge on those bits; a reset clears the shadow array
(``efuse_shadow_regs`` reset branch), so a resense drives the falling edge and
the rising edge again.

Four groups are held back, each because setting it would break the path the
leaf itself runs on:

* ``LC_STATE`` -- the lifecycle nibble is differentially encoded and only
  seven raw codes are legal. It is set through ``lc_raw`` instead.
* ``LOCKS`` / ``LOCKS_SPARE`` -- a lock bit closes a field to the very
  accesses this image is sensed for.
* ``TRANSIENT_RMA_EN`` -- held clear, so the lifecycle nibble cannot move on
  a token match part way through the run.
* ``SIP_DIS`` / ``SYS_DIS`` -- patterned only across the two debug groups
  (bits 47:1). Bit 0 is ``SEP_DBG``, which gates the inbound filter, and the
  function group at bits 63:48 disables hardware this leaf needs, so both
  stay clear.

The pattern is a fixed function of the field layout, not of the seed: the
leaf's value is covering the array, and a per-seed choice would cover a
different part of it on every run. ``seed`` is carried so the rest of the
image (the fields this config does not pin) stays the ordinary seeded random
one and the staged image matches the test's golden.
"""

from __future__ import annotations

from sep_efuse_image import SepEfuseImage
import sep_reg

WORD_A = 0x5555_5555
WORD_B = 0xAAAA_AAAA

# Fields this config must not pattern; see the module docstring.
_HELD_BACK = ("LC_STATE", "LOCKS", "LOCKS_SPARE", "TRANSIENT_RMA_EN", "SIP_DIS", "SYS_DIS")

# SIP_DIS / SYS_DIS carry the pattern only over the DBG_1 (bits 23:0) and
# DBG_2 (bits 47:24) groups of the feature vector, with bit 0 (SEP_DBG) and the
# function group (bits 63:48) left clear.
DIS_PATTERN = 0x0000_AAAA_AAAA_AAAA


def _field_names() -> tuple[str, ...]:
    """Every eFuse map field, from the generated register header."""
    pfx, sfx = "SEP_EFUSE_MAP_", "_REG_OFFSET"
    return tuple(
        sorted(
            (n[len(pfx) : -len(sfx)] for n in dir(sep_reg) if n.startswith(pfx) and n.endswith(sfx))
        )
    )


class SepCovEfuseDiversityCfg:
    """The ``select_efuse_image(fixed=...)`` pins for the diversity leaf."""

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def image_fixed(self) -> dict[str, int]:
        fixed: dict[str, int] = {}
        word_index = 0
        for name in _field_names():
            if name in _HELD_BACK:
                continue
            n_words = SepEfuseImage.field(name).n_words
            value = 0
            for k in range(n_words):
                word = WORD_A if ((word_index + k) % 2 == 0) else WORD_B
                value |= word << (32 * k)
            fixed[name] = value
            word_index += n_words
        fixed["LOCKS"] = 0
        fixed["LOCKS_SPARE"] = 0
        fixed["TRANSIENT_RMA_EN"] = 0
        fixed["SIP_DIS"] = DIS_PATTERN
        fixed["SYS_DIS"] = DIS_PATTERN
        return fixed

    def summary(self) -> str:
        fixed = self.image_fixed()
        return (
            f"seed={self.seed} patterned_fields={len(fixed) - 5} "
            f"dis_pattern=0x{DIS_PATTERN:016x}"
        )


def _selftest() -> None:
    fixed = SepCovEfuseDiversityCfg(1).image_fixed()
    for held in _HELD_BACK:
        assert held in fixed or held == "LC_STATE", f"{held} must be pinned or set via lc_raw"
    assert "LC_STATE" not in fixed
    assert fixed["LOCKS"] == 0 and fixed["LOCKS_SPARE"] == 0
    assert fixed["TRANSIENT_RMA_EN"] == 0
    # Bit 0 is SEP_DBG and the function group is bits 63:48; both stay clear.
    assert fixed["SYS_DIS"] & 1 == 0
    assert fixed["SYS_DIS"] >> 48 == 0
    # Every patterned field is a whole number of alternating words.
    spare0 = fixed["SPARE0"]
    assert spare0 & 0xFFFF_FFFF in (WORD_A, WORD_B)


_selftest()
