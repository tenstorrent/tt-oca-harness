# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse program x write-lock matrix config (spare/test field only).

Every invocation walks unlocked-program then write-lock-reject on **each** of
SPARE0..SPARE8, in order. Never LC_STATE. Lock slot n owns write-lock at bit 2n
of the 96-bit LOCKS+LOCKS_SPARE vector (``hw/sys/sep/doc/otp_fuse_controller.adoc``:
``LOCKS`` slots 0–31, ``LOCKS_SPARE`` slots 32–40). Spare k is slot 32+k, so
its write-lock is OTP bit (32+k)*2. The same slot map lives in
``env/sep_locked_field_irq.py``, which takes the spare count from the generated
eFuse map.

Walking all nine is what makes the slot numbering falsifiable. Selecting one
spare per seed samples the lane instead: a lock bit wired to the wrong slot is
caught only on the run that happens to draw that spare, and reseeding widens the
sample without ever guaranteeing the set. Ordering the walk also makes it a
containment proof for free -- spare k+1 is programmed after spare k has been
locked, so a lock that reached beyond its own slot fails the next iteration.

Only the bit offsets within each spare stay seed-selected; which spares are
visited does not depend on the seed.
"""

from __future__ import annotations

from env.sep_efuse_image import SepEfuseImage
from env.sep_locked_field_irq import SPARE_COUNT, spare_write_lock_bit
from env.sep_seeded_rng import SepSeededRng


def spare_field_name(spare_idx: int) -> str:
    return f"SPARE{spare_idx}"


def field_bit_addr(field_name: str, bit_offset: int) -> int:
    """Global OTP bit index of ``field_name[bit_offset]``."""
    fld = SepEfuseImage.field(field_name)
    nbits = fld.n_words * 32
    if not 0 <= bit_offset < nbits:
        raise ValueError(f"{field_name} bit {bit_offset} out of range 0..{nbits - 1}")
    return fld.word * 32 + bit_offset


class SepEfuseSpareCell:
    """One spare's program / lock / reject addresses."""

    def __init__(self, spare_idx: int, program_bit: int, reject_bit: int) -> None:
        self.spare_idx = spare_idx
        self.field = spare_field_name(spare_idx)
        self.program_bit = program_bit
        self.reject_bit = reject_bit
        self.lock_bit = spare_write_lock_bit(spare_idx)
        self.program_addr = field_bit_addr(self.field, program_bit)
        self.reject_addr = field_bit_addr(self.field, reject_bit)
        assert self.field != "LC_STATE"
        assert self.lock_bit != self.program_addr

    def summary(self) -> str:
        return (
            f"{self.field} program_bit={self.program_bit} "
            f"reject_bit={self.reject_bit} write_lock_otp_bit={self.lock_bit}"
        )


class SepEfuseProgramLockCfg:
    """Single source of truth for the spare-field lock x program walk."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.cells: list[SepEfuseSpareCell] = []
        for spare_idx in range(SPARE_COUNT):
            fld = SepEfuseImage.field(spare_field_name(spare_idx))
            nbits = fld.n_words * 32
            program_bit = rng.randrange(nbits)
            reject_bit = rng.randrange(nbits)
            if reject_bit == program_bit:
                reject_bit = (program_bit + 1) % nbits
            self.cells.append(SepEfuseSpareCell(spare_idx, program_bit, reject_bit))

    @property
    def fields(self) -> list[str]:
        return [c.field for c in self.cells]

    def summary(self) -> str:
        return f"seed={self.seed} spares={SPARE_COUNT} " + "; ".join(
            c.summary() for c in self.cells
        )


def _selftest() -> None:
    assert spare_write_lock_bit(0) == 64
    assert spare_write_lock_bit(7) == 78
    # Slot 40, the last LOCKS_SPARE slot in otp_fuse_controller.adoc.
    assert spare_write_lock_bit(8) == 80
    fld = SepEfuseImage.field("SPARE0")
    assert field_bit_addr("SPARE0", 0) == fld.word * 32
    cfg = SepEfuseProgramLockCfg(1)
    assert SPARE_COUNT == 9, f"walk covers {SPARE_COUNT} spares, spec gives SPARE0..SPARE8"
    # Every spare is visited, whatever the seed -- that is the point of the walk.
    assert [c.spare_idx for c in cfg.cells] == list(range(SPARE_COUNT))
    assert cfg.fields == [f"SPARE{i}" for i in range(SPARE_COUNT)]
    for c in cfg.cells:
        assert c.program_bit != c.reject_bit
        assert "LC_STATE" not in c.field
    # Each spare owns a distinct write-lock bit.
    assert len({c.lock_bit for c in cfg.cells}) == SPARE_COUNT


_selftest()
