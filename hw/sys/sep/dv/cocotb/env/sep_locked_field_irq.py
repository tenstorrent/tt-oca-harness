# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-field IRQ path config (OTP image pins + spare selection).

Importable from the pre-sim staging hook: no cocotb. The AXI driver lives in
``seq_lib/sep_locked_field_irq_seq.py``.

Both leaves share this object. The constructor draws four distinct spares
(write-lock, read-lock, unlocked contrast, SECURE_TM LOCKS_SPARE control)
and ``image_fixed()`` stages ``SIP_DIS`` / ``SYS_DIS`` at 0 so the
SECURE_TM payloads always change a bit. That is the seed-to-image map for
``sep_locked_field_access_irq_path_test`` as well.
"""

from __future__ import annotations

from sep_efuse_field_map import spec_secure_tm_blocked
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


# Fields the specification says must refuse a write while SECURE_TM=1
# (periphs.adoc). LOCKS and LOCKS_SPARE are one 96-bit LOCK field.
SECURE_TM_LOCK_FIELDS = spec_secure_tm_blocked()

# LC_STATE bytes [31:8] OR-merge as ordinary shadow bytes and do not disturb the
# lifecycle nibble, so they are the safe payload for this field.
LC_STATE_UPPER_MASK = 0xFFFF_FF00

# Lock slot 31 is SEP_SYS_ID (periphs.adoc); write-lock is bit 2n = 62.
SEP_SYS_ID_WRITE_LOCK_BIT = 62
SEP_SYS_ID_WRITE_LOCK_WORD = SEP_SYS_ID_WRITE_LOCK_BIT // 32


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
        idxs.remove(self.unlocked_spare)
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

        # SECURE_TM leaf. A fourth spare, distinct from the three above, carries
        # the LOCKS_SPARE positive control: setting its write-lock bit at
        # secure_tm=0 proves the aperture is writable before the strap goes up.
        self.sectm_spare = rng.choice(idxs)
        # Four distinct spares. Each rng.choice above removes its pick, so a
        # collision means two roles share one field and the contrast leg
        # compares a field against itself.
        assert len(used | {self.sectm_spare}) == 4
        self.sectm_locks_spare_payload = 1 << _locks_spare_bit(
            spare_write_lock_bit(self.sectm_spare)
        )
        # LOCKS deny target: slot 31 (SEP_SYS_ID) write-lock. Nothing later in
        # the leaf reads that field, so a DUT that wrongly accepts the write
        # fails the check rather than corrupting a later one.
        self.sectm_locks_payload = 1 << (SEP_SYS_ID_WRITE_LOCK_BIT % 32)
        # field -> (word index within the field, 32-bit payload).
        self.sectm_payload = {
            "LOCKS": (SEP_SYS_ID_WRITE_LOCK_WORD, self.sectm_locks_payload),
            "LOCKS_SPARE": (0, self.sectm_locks_spare_payload),
            # Masking a random word to [31:8] can clear every set bit, which
            # would abort the leaf on the assert below instead of exercising
            # the lock. Seed one bit inside the allowed region so the payload
            # is non-zero by construction and the assert stays a check.
            "LC_STATE": (
                0,
                (_nonzero_pattern(rng, forbidden) & LC_STATE_UPPER_MASK) | 0x0000_0100,
            ),
            "SIP_DIS": (0, _nonzero_pattern(rng, forbidden)),
            "SYS_DIS": (0, _nonzero_pattern(rng, forbidden)),
        }
        assert self.sectm_payload["LC_STATE"][1] != 0, "LC_STATE payload must touch bytes [31:8]"
        assert set(self.sectm_payload) == set(SECURE_TM_LOCK_FIELDS)

    def image_fixed(self) -> dict[str, int]:
        return {
            self.write_field: self.write_pattern,
            self.read_field: self.read_pattern,
            self.unlocked_field: self.unlocked_pattern,
            "LOCKS_SPARE": self.locks_spare,
            # Staged at zero so the SECURE_TM payloads below always change a
            # bit. These fields OR-merge, so a randomized stage whose bits
            # already cover the payload leaves the readback equal to the
            # pre-write value and fails the positive control for a reason that
            # has nothing to do with the write path.
            "SIP_DIS": 0,
            "SYS_DIS": 0,
        }

    def summary(self) -> str:
        return (
            f"seed={self.seed} write={self.write_field} read={self.read_field} "
            f"unlocked={self.unlocked_field} LOCKS_SPARE=0x{self.locks_spare:04x} "
            f"sectm_spare=SPARE{self.sectm_spare}"
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
    assert cfg.sectm_spare not in (cfg.write_spare, cfg.read_spare, cfg.unlocked_spare)
    assert cfg.sectm_locks_spare_payload & cfg.locks_spare == 0
    assert cfg.sectm_payload["LC_STATE"][1] & ~LC_STATE_UPPER_MASK == 0
    assert all(v != 0 for _w, v in cfg.sectm_payload.values())
    assert cfg.sectm_payload["LOCKS"][0] == 1


_selftest()
