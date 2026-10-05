# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Locked-field IRQ path config (OTP image pins + spare selection).

Importable from the pre-sim staging hook: no cocotb. The AXI driver lives in
``seq_lib/sep_locked_field_irq_seq.py``.

``sep_locked_field_access_irq_path_test`` and its plusarg variant
``sep_efuse_secure_tm_write_lock_test`` share this object. The constructor
draws four distinct spares (write-lock, read-lock, unlocked contrast, SECURE_TM
LOCKS_SPARE control) and ``image_fixed()`` stages ``SIP_DIS`` / ``SYS_DIS`` at 0
so the SECURE_TM payloads always change a bit. ``dv_sim_prestage.py`` uses the
same seed-to-image map.
"""

from __future__ import annotations

import re

from sep_efuse_field_map import spec_secure_tm_blocked
from sep_efuse_image import LOCK_BITS_PER_SLOT
from sep_reg_meta import RegBlock, sep_reg  # the generated export, path set up by sep_reg_meta
from sep_seeded_rng import SepSeededRng
from sep_spec_tables import agg_from_pic

IRQ_LOCKED_FIELD = agg_from_pic("Locked field access")
# Error-slave read data named by hw/ip/efuse/doc/architecture.adoc (access
# control). It is not an expected value here: no staged pattern may equal it, so
# a read-lock readback that returns it still differs from the stored field.
DENY_DATA_MARKER = 0xBADCAB1E


def _spare_count() -> int:
    """Number of spare fuse fields, from the generated SystemRDL export.

    otp_fuse_controller.adoc gives LOCKS_SPARE slots 32-40, one per spare
    field SPARE0..SPARE8. The export carries the same set twice: the
    ``SEP_EFUSE_MAP_SPARE<k>`` field offsets and the ``spare<k>_write_lock``
    bits of LOCKS_SPARE. Both must agree, and the indices must run from 0
    without a gap, or a spare is left out of every walk that uses the count.
    """
    fields = sorted(
        int(m.group(1))
        for n in dir(sep_reg)
        if (m := re.fullmatch(r"SEP_EFUSE_MAP_SPARE(\d+)_REG_OFFSET", n))
    )
    locks = sorted(
        int(m.group(1))
        for name, *_ in sep_reg.SEP_EFUSE_MAP_LOCKS_SPARE_reg_t._fields_
        if (m := re.fullmatch(r"spare(\d+)_write_lock", name))
    )
    if not fields or fields != list(range(len(fields))) or fields != locks:
        raise RuntimeError(
            f"spare fields {fields} and LOCKS_SPARE write-locks {locks} do not "
            "form one gap-free set in the generated eFuse map"
        )
    return len(fields)


SPARE_COUNT = _spare_count()
# otp_fuse_controller.adoc LOCKS slots 0–31, LOCKS_SPARE slots 32–40. Spare k is slot 32+k.
SPARE0_SLOT = 32
# LOCKS_SPARE starts at bit 64 of the 96-bit LOCKS+LOCKS_SPARE vector.
_LOCKS_SPARE_VECTOR_LSB = SPARE0_SLOT * LOCK_BITS_PER_SLOT


def spare_field_name(spare_idx: int) -> str:
    return f"SPARE{spare_idx}"


def spare_write_lock_bit(spare_idx: int) -> int:
    """Global lock-vector bit of spare ``k``'s write-lock (otp_fuse_controller.adoc)."""
    if not 0 <= spare_idx < SPARE_COUNT:
        raise ValueError(f"spare_idx {spare_idx} not in 0..{SPARE_COUNT - 1}")
    return (SPARE0_SLOT + spare_idx) * LOCK_BITS_PER_SLOT


def spare_read_lock_bit(spare_idx: int) -> int:
    """Global lock-vector bit of spare ``k``'s read-lock."""
    return spare_write_lock_bit(spare_idx) + 1


def spare_zero_pins() -> dict[str, int]:
    """OTP image pins that stage every spare field at 0."""
    return {spare_field_name(k): 0 for k in range(SPARE_COUNT)}


def _locks_spare_bit(vector_bit: int) -> int:
    """LOCKS_SPARE bit of a spare lock (vector bits 64..81 -> 0..17 for 9 spares)."""
    top = _LOCKS_SPARE_VECTOR_LSB + SPARE_COUNT * LOCK_BITS_PER_SLOT
    if not _LOCKS_SPARE_VECTOR_LSB <= vector_bit < top:
        raise ValueError(
            f"spare lock vector bit {vector_bit} not in {_LOCKS_SPARE_VECTOR_LSB}..{top - 1}"
        )
    return vector_bit - _LOCKS_SPARE_VECTOR_LSB


def _nonzero_pattern(rng: SepSeededRng, forbidden: set[int]) -> int:
    for _ in range(8):
        v = rng.getrandbits(32)
        if v not in forbidden and v != 0 and v != DENY_DATA_MARKER:
            return v
    for v in (0xA5A5A5A5, 0x5A5A5A5A, 0x3C3C3C3C, 0xC3C3C3C3):
        if v not in forbidden:
            return v
    raise ValueError("no fallback pattern left outside the forbidden set")


# Fields the specification says must refuse a write while SECURE_TM=1
# (otp_fuse_controller.adoc). LOCKS and LOCKS_SPARE are one 96-bit LOCK field.
SECURE_TM_LOCK_FIELDS = spec_secure_tm_blocked()

_EFUSE_MAP = RegBlock("SEP_EFUSE_MAP")

# LC_STATE bytes [31:8] (the RDL rsvd field) OR-merge as ordinary shadow bytes
# and do not disturb the lifecycle nibble, so they are the safe payload for
# this field.
LC_STATE_UPPER_MASK = _EFUSE_MAP.field_mask("LC_STATE", "rsvd")

# Lock slot 31 is SEP_SYS_ID (otp_fuse_controller.adoc); its write-lock is the
# LOCKS.SEP_SYS_ID_WRITE_LOCK field (bit 2n = 62).
SEP_SYS_ID_WRITE_LOCK_BIT = _EFUSE_MAP.field_lsb("LOCKS", "sep_sys_id_write_lock")
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
    # otp_fuse_controller.adoc: nine spares, slots 32-40.
    assert SPARE_COUNT == 9, f"SPARE_COUNT={SPARE_COUNT}, spec gives SPARE0..SPARE8"
    assert spare_write_lock_bit(0) == 64
    assert spare_read_lock_bit(0) == 65
    assert spare_read_lock_bit(SPARE_COUNT - 1) == 81
    assert _locks_spare_bit(64) == 0
    assert _locks_spare_bit(65) == 1
    assert _locks_spare_bit(81) == 17
    assert set(spare_zero_pins()) == {f"SPARE{k}" for k in range(SPARE_COUNT)}
    cfg = SepLockedFieldIrqCfg(1)
    assert len({cfg.write_spare, cfg.read_spare, cfg.unlocked_spare}) == 3
    assert cfg.locks_spare != 0
    for pat in (cfg.write_pattern, cfg.read_pattern, cfg.unlocked_pattern, cfg.unlocked_write):
        assert pat not in (0, DENY_DATA_MARKER)
    pins = cfg.image_fixed()
    assert pins["LOCKS_SPARE"] == cfg.locks_spare
    assert cfg.sectm_spare not in (cfg.write_spare, cfg.read_spare, cfg.unlocked_spare)
    assert cfg.sectm_locks_spare_payload & cfg.locks_spare == 0
    assert cfg.sectm_payload["LC_STATE"][1] & ~LC_STATE_UPPER_MASK == 0
    assert all(v != 0 for _w, v in cfg.sectm_payload.values())
    assert cfg.sectm_payload["LOCKS"][0] == 1


_selftest()
