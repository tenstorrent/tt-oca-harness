# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-field IRQ path config (OTP image pins + spare selection).

Importable from the pre-sim staging hook: no cocotb. The AXI driver lives in
``seq_lib/sep_locked_field_irq_seq.py``.
"""

from __future__ import annotations

from sep_efuse_image import LOCK_BITS_PER_SLOT
from sep_seeded_rng import SepSeededRng

SENTINEL = 0xBADCAB1E
IRQ_LOCKED_FIELD = 33
RESP_OKAY = 0
SPARE_COUNT = 8
SPARE0_SLOT = 32


def spare_field_name(spare_idx: int) -> str:
    return f"SPARE{spare_idx}"


def spare_write_lock_bit(spare_idx: int) -> int:
    """Global lock-vector bit of spare ``k``'s write-lock."""
    if not 0 <= spare_idx < SPARE_COUNT:
        raise ValueError(f"spare_idx {spare_idx} not in 0..{SPARE_COUNT - 1}")
    return (SPARE0_SLOT + spare_idx) * LOCK_BITS_PER_SLOT


def spare_read_lock_bit(spare_idx: int) -> int:
    """Global lock-vector bit of spare ``k``'s read-lock."""
    return spare_write_lock_bit(spare_idx) + 1


def _locks_spare_bit(vector_bit: int) -> int:
    """LOCKS_SPARE bit of a spare lock (96-bit vector bits 64..79 -> 0..15)."""
    if not 64 <= vector_bit < 80:
        raise ValueError(f"spare lock vector bit {vector_bit} not in 64..79")
    return vector_bit - 64


def _nonzero_pattern(rng: SepSeededRng, forbidden: set[int]) -> int:
    for _ in range(8):
        v = rng.getrandbits(32)
        if v not in forbidden and v != 0 and v != SENTINEL:
            return v
    return 0xA5A5A5A5


class SepLockedFieldIrqCfg:
    """Single source of truth for the OTP image pins and the checker fields."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        idxs = list(range(SPARE_COUNT))
        self.write_spare = rng.choice(idxs)
        idxs.remove(self.write_spare)
        self.read_spare = rng.choice(idxs)
        idxs.remove(self.read_spare)
        self.unlocked_spare = rng.choice(idxs)
        used = {self.write_spare, self.read_spare, self.unlocked_spare}
        assert len(used) == 3
        self.write_field = spare_field_name(self.write_spare)
        self.read_field = spare_field_name(self.read_spare)
        self.unlocked_field = spare_field_name(self.unlocked_spare)
        forbidden: set[int] = set()
        self.write_pattern = _nonzero_pattern(rng, forbidden)
        forbidden.add(self.write_pattern)
        self.read_pattern = _nonzero_pattern(rng, forbidden)
        forbidden.add(self.read_pattern)
        self.unlocked_pattern = _nonzero_pattern(rng, forbidden)
        forbidden.add(self.unlocked_pattern)
        self.unlocked_write = _nonzero_pattern(rng, forbidden)
        locks = 0
        locks |= 1 << _locks_spare_bit(spare_write_lock_bit(self.write_spare))
        locks |= 1 << _locks_spare_bit(spare_read_lock_bit(self.read_spare))
        self.locks_spare = locks

    def image_fixed(self) -> dict[str, int]:
        return {
            self.write_field: self.write_pattern,
            self.read_field: self.read_pattern,
            self.unlocked_field: self.unlocked_pattern,
            "LOCKS_SPARE": self.locks_spare,
        }

    def summary(self) -> str:
        return (
            f"seed={self.seed} write={self.write_field} read={self.read_field} "
            f"unlocked={self.unlocked_field} LOCKS_SPARE=0x{self.locks_spare:04x}"
        )


def _selftest() -> None:
    assert spare_write_lock_bit(0) == 64
    assert spare_read_lock_bit(0) == 65
    assert _locks_spare_bit(64) == 0
    assert _locks_spare_bit(65) == 1
    cfg = SepLockedFieldIrqCfg(1)
    assert len({cfg.write_spare, cfg.read_spare, cfg.unlocked_spare}) == 3
    assert cfg.locks_spare != 0
    assert cfg.write_pattern not in (0, SENTINEL)
    pins = cfg.image_fixed()
    assert pins["LOCKS_SPARE"] == cfg.locks_spare


_selftest()
