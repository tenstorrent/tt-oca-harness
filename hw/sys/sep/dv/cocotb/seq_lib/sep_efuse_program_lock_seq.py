# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse program x write-lock matrix config (spare/test field only).

RAND-REP: every seed walks unlocked-program then write-lock-reject on one
legal spare field (SPARE0..SPARE7). Never LC_STATE. Lock slot n owns
write-lock at bit 2n of the 96-bit LOCKS+LOCKS_SPARE vector
(``hw/sys/sep/doc/periphs.adoc``, ``sep_efuse_pkg``). Spare k is slot 32+k,
so its write-lock is OTP bit (32+k)*2.

The spare field and the two program bit offsets are seed-selected. The two
discrete cells are walked every invocation.
"""

from __future__ import annotations

from env.sep_efuse_image import LOCK_BITS_PER_SLOT, SepEfuseImage
from env.sep_seeded_rng import SepSeededRng

SPARE_COUNT = 8
SPARE0_SLOT = 32


def spare_field_name(spare_idx: int) -> str:
    return f"SPARE{spare_idx}"


def spare_write_lock_bit(spare_idx: int) -> int:
    """Global OTP bit index of spare ``k``'s write-lock (LOCKS_SPARE)."""
    if not 0 <= spare_idx < SPARE_COUNT:
        raise ValueError(f"spare_idx {spare_idx} not in 0..{SPARE_COUNT - 1}")
    return (SPARE0_SLOT + spare_idx) * LOCK_BITS_PER_SLOT


def field_bit_addr(field_name: str, bit_offset: int) -> int:
    """Global OTP bit index of ``field_name[bit_offset]``."""
    fld = SepEfuseImage.field(field_name)
    nbits = fld.n_words * 32
    if not 0 <= bit_offset < nbits:
        raise ValueError(f"{field_name} bit {bit_offset} out of range 0..{nbits - 1}")
    return fld.word * 32 + bit_offset


class SepEfuseProgramLockCfg:
    """Single source of truth for the spare-field lock x program walk."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.spare_idx = rng.randrange(SPARE_COUNT)
        self.field = spare_field_name(self.spare_idx)
        fld = SepEfuseImage.field(self.field)
        nbits = fld.n_words * 32
        self.program_bit = rng.randrange(nbits)
        reject_bit = rng.randrange(nbits)
        if reject_bit == self.program_bit:
            reject_bit = (self.program_bit + 1) % nbits
        self.reject_bit = reject_bit
        self.lock_bit = spare_write_lock_bit(self.spare_idx)
        self.program_addr = field_bit_addr(self.field, self.program_bit)
        self.reject_addr = field_bit_addr(self.field, self.reject_bit)
        assert self.field != "LC_STATE"
        assert self.lock_bit != self.program_addr

    def summary(self) -> str:
        return (
            f"seed={self.seed} field={self.field} program_bit={self.program_bit} "
            f"reject_bit={self.reject_bit} write_lock_otp_bit={self.lock_bit}"
        )


def _selftest() -> None:
    assert spare_write_lock_bit(0) == 64
    assert spare_write_lock_bit(7) == 78
    fld = SepEfuseImage.field("SPARE0")
    assert field_bit_addr("SPARE0", 0) == fld.word * 32
    cfg = SepEfuseProgramLockCfg(1)
    assert cfg.field.startswith("SPARE")
    assert cfg.program_bit != cfg.reject_bit
    assert "LC_STATE" not in cfg.field


_selftest()
