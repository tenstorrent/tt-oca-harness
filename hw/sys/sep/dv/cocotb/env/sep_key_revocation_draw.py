# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed -> (revocation bitmap, primary slot, backup slot) for the key-revocation random test.

The testcase and the pre-sim hook ``dv_sim_prestage.py`` both call :func:`draw`, so the
two cannot drift. The efuse bank model waits for ``rst_ni`` before its ``$readmemh``,
so the DUT senses the testcase's golden image; the testcase asserts that the golden
matches the hook's pre-staged copy word for word, which proves both processes ran the
same draw.

Bare sibling imports only (``sep_seeded_rng``, not ``env.sep_seeded_rng``): the pre-sim
process loads this module by file path, where cocotb and the ``env`` package do not
import.

The draw picks one of four outcome classes first and then solves for a stimulus in it,
so no seed repeats what the directed
``sep_firmware_{primary,backup}_pubkey_rom_{0..5}_revoked_key_test`` tests prove:

  * ``clean_proceed`` -- ``bitmap == 0``: a part with nothing revoked is not refused;
  * ``noisy_proceed`` -- ``bitmap[p] == 0`` and ``bitmap != 0``: a set bit that is not
    the selected slot's must not block the boot;
  * ``primary_failover`` -- ``bitmap[p] == 1``, ``bitmap[b] == 0``: the selected slot is
    refused and a different unrevoked slot still boots;
  * ``both_revoked_terminal`` -- ``bitmap[p] == 1`` and ``bitmap[b] == 1``: the backup
    path also applies the revocation check.

Clean and noisy proceed share one outcome; they are separate classes only for coverage.

Bits 6 and 7 carry no ROM key slot: the ROM rejects an index at or above
``PUBK_SEL_NUM_ROM_KEYS`` before the revocation check, so setting them must change
nothing. The noisy class draws an inert-bits-only sub-mode half the time, because a
uniform draw over the seven non-primary bits reaches it on only 3 of 127 seeds.

Limitation: an inert-bits-only seed can close a ``noisy_proceed__pN`` bin without
showing that another ROM slot's bit is ignored; see :data:`CLOSURE_CAVEATS`.
"""

from __future__ import annotations

from typing import Dict, NamedTuple, Tuple

# Bare sibling import: cocotb/env is on sys.path in the sim (sep_sim_cfg.toml
# python_paths) and is inserted explicitly by the prestage hook.
from sep_seeded_rng import SepSeededRng

# public_key_select for ROM key N is N, the key's revocation bitmap slot.
PUBK_SEL_ROM_KEY = 0
PUBK_SEL_NUM_ROM_KEYS = 6

# sep_efuse_map.rdl: CHIPLET_PUBK_REVOKE.select[7:0] is the ROM chiplet-creator
# classical key bitmap. [15:8] are PQC keys and 16+ are the fused keys, so
# nothing here may be derived by counting past bit 7.
REVOKE_BITMAP_WIDTH = 8
ROM_SLOT_BIT_MASK = (1 << PUBK_SEL_NUM_ROM_KEYS) - 1  # 0x3f
INERT_BIT_MASK = ((1 << REVOKE_BITMAP_WIDTH) - 1) & ~ROM_SLOT_BIT_MASK  # 0xc0

CLASS_CLEAN_PROCEED = "clean_proceed"
CLASS_NOISY_PROCEED = "noisy_proceed"
CLASS_PRIMARY_FAILOVER = "primary_failover"
CLASS_BOTH_REVOKED_TERMINAL = "both_revoked_terminal"
CLASSES: Tuple[str, ...] = (
    CLASS_CLEAN_PROCEED,
    CLASS_NOISY_PROCEED,
    CLASS_PRIMARY_FAILOVER,
    CLASS_BOTH_REVOKED_TERMINAL,
)

# The three observable outcomes; clean and noisy proceed map to the same one.
OUTCOME_PROCEED = "proceed"
OUTCOME_FAILOVER = "failover"
OUTCOME_TERMINAL = "terminal"

# Lifecycle the image is pinned to: PROD is what makes SEP ROM enforce signature
# verification rather than letting the manifest ask for it.
LC_RAW_PROD = 0x1

# Coverage bin names. The terminal-relation and inert-noise bins are additional to
# the class x primary-slot grid, not a partition of it, so a run can hit up to
# three bins.
BIN_TERMINAL_B_EQ_P = "terminal_backup_eq_primary"
BIN_TERMINAL_B_NE_P = "terminal_backup_ne_primary"
BIN_INERT_NOISE_ONLY = "inert_noise_only"


class KeyRevocationDraw(NamedTuple):
    """One seed's stimulus, and the class its outcome must land in."""

    bitmap: int
    primary_slot: int
    backup_slot: int
    expected_class: str

    @property
    def expected_outcome(self) -> str:
        return outcome_of(self.expected_class)

    def describe(self) -> str:
        return (
            f"bitmap=0x{self.bitmap:02x} primary_slot={self.primary_slot} "
            f"backup_slot={self.backup_slot} class={self.expected_class} "
            f"outcome={self.expected_outcome}"
        )


def bit_set(bitmap: int, slot: int) -> bool:
    """Reproduce the ROM's ``revoke & (1u << index)`` test for one slot."""
    return bool(bitmap & (1 << slot))


def classify(bitmap: int, primary_slot: int, backup_slot: int) -> str:
    """Return the class of a stimulus; total over every (bitmap, p, b).

    Only the primary's and backup's bits decide the outcome; ``bitmap != 0`` only
    splits proceed into two coverage classes (see :func:`outcome_of`).
    """
    _check_slot(primary_slot, "primary_slot")
    _check_slot(backup_slot, "backup_slot")
    if not bit_set(bitmap, primary_slot):
        return CLASS_CLEAN_PROCEED if bitmap == 0 else CLASS_NOISY_PROCEED
    if bit_set(bitmap, backup_slot):
        return CLASS_BOTH_REVOKED_TERMINAL
    return CLASS_PRIMARY_FAILOVER


def outcome_of(cls: str) -> str:
    """Observable outcome for a class. Clean and noisy proceed share one."""
    if cls in (CLASS_CLEAN_PROCEED, CLASS_NOISY_PROCEED):
        return OUTCOME_PROCEED
    if cls == CLASS_PRIMARY_FAILOVER:
        return OUTCOME_FAILOVER
    if cls == CLASS_BOTH_REVOKED_TERMINAL:
        return OUTCOME_TERMINAL
    raise ValueError(f"unknown coverage class {cls!r}")


def coverage_bins(bitmap: int, primary_slot: int, backup_slot: int) -> Tuple[str, ...]:
    """Bins a stimulus covers, out of the 27 in :func:`all_bins`."""
    cls = classify(bitmap, primary_slot, backup_slot)
    hit = [f"{cls}__p{primary_slot}"]
    if cls == CLASS_BOTH_REVOKED_TERMINAL:
        hit.append(BIN_TERMINAL_B_EQ_P if backup_slot == primary_slot else BIN_TERMINAL_B_NE_P)
    # The bit the ROM cannot see, set with no slot bit beside it: the only
    # stimulus that can show bits 6 and 7 are inert rather than untested.
    if (bitmap & ROM_SLOT_BIT_MASK) == 0 and (bitmap & INERT_BIT_MASK) != 0:
        hit.append(BIN_INERT_NOISE_ONLY)
    return tuple(hit)


CLOSURE_CAVEATS: Tuple[str, ...] = (
    "A noisy_proceed__pN bin can be closed by a seed whose only set bits are 6 "
    "and 7, which carry no ROM slot and so do not exercise the property that "
    "class exists for. Six of the 24 grid bins are affected. Before claiming "
    "closure, either split the noisy bins by sub-mode (27 -> 33) or require "
    "bitmap & 0x3f != 0 for a noisy_proceed bin to count.",
)


def all_bins() -> Tuple[str, ...]:
    """The full 27-bin closure set: 4 classes x 6 primary slots, plus 3.

    Read :data:`CLOSURE_CAVEATS` before treating a full set as closure.
    """
    grid = tuple(f"{cls}__p{slot}" for cls in CLASSES for slot in range(PUBK_SEL_NUM_ROM_KEYS))
    return grid + (BIN_TERMINAL_B_EQ_P, BIN_TERMINAL_B_NE_P, BIN_INERT_NOISE_ONLY)


def efuse_fixed(bitmap: int) -> Dict[str, int]:
    """eFuse fields this stimulus pins, for ``SepEfuseImage.randomize(fixed=)``.

    Both readers take these from here, so the pre-staged image and the golden match.
    Every extra pin narrows the randomization this test exists to perform:

      * ``CHIPLET_PUBK_REVOKE`` is the stimulus;
      * ``BL1_VERSION`` 0 keeps the rollback check, which runs before key selection,
        from rejecting a slot first;
      * ``SBOOT_DIS`` 0 keeps the crypto chain from being skipped.

    The caller pins lifecycle PROD through ``lc_raw``. Every other word stays random,
    the fused key digests and ``STATUS_RPT`` included: the ROM reads them only on
    paths this stimulus never selects. ``pll_init()`` reads its fuse only when the
    ``bl0_pll_clk`` strap is set; this TB leaves it clear, so the run prints
    ``CLK_REFCLK``.
    """
    _check_bitmap(bitmap)
    return {
        "CHIPLET_PUBK_REVOKE": bitmap,
        "BL1_VERSION": 0,
        "SBOOT_DIS": 0,
    }


def draw(seed: int) -> KeyRevocationDraw:
    """Derive one seed's stimulus. Pure: same seed, same result, either process."""
    rng = SepSeededRng(seed)
    cls = CLASSES[rng.randrange(len(CLASSES))]
    primary = rng.randrange(PUBK_SEL_NUM_ROM_KEYS)

    if cls == CLASS_CLEAN_PROCEED:
        bitmap = 0
        backup = rng.randrange(PUBK_SEL_NUM_ROM_KEYS)
    elif cls == CLASS_NOISY_PROCEED:
        # The primary boots, so the backup's bit is free; only the primary's must
        # stay clear and the word must be non-zero.
        inert_only = bool(rng.getrandbits(1))
        pool = _inert_bits() if inert_only else _bits_except((primary,))
        bitmap = _nonempty_subset(rng, pool)
        backup = rng.randrange(PUBK_SEL_NUM_ROM_KEYS)
    elif cls == CLASS_PRIMARY_FAILOVER:
        backup = _other_slot(rng, primary)
        bitmap = (1 << primary) | _subset(rng, _bits_except((primary, backup)))
    else:
        backup = rng.randrange(PUBK_SEL_NUM_ROM_KEYS)
        bitmap = (1 << primary) | (1 << backup)
        bitmap |= _subset(rng, _bits_except((primary, backup)))

    landed = classify(bitmap, primary, backup)
    # The solver and classify() are independent; a disagreement means this seed's
    # expectation is wrong, so fail before the simulation starts.
    assert landed == cls, (
        f"seed {seed}: the draw asked for class {cls} but bitmap=0x{bitmap:02x} "
        f"with primary_slot={primary} backup_slot={backup} classifies as {landed}"
    )
    return KeyRevocationDraw(bitmap, primary, backup, cls)


# --- internals -------------------------------------------------------------
def _check_slot(slot: int, what: str) -> None:
    if not 0 <= slot < PUBK_SEL_NUM_ROM_KEYS:
        raise ValueError(
            f"{what}={slot} is outside the ROM key table [0, {PUBK_SEL_NUM_ROM_KEYS}); "
            f"an out-of-range index is the separate BAD_KEY_IDX arm, not a "
            f"revocation stimulus"
        )


def _check_bitmap(bitmap: int) -> None:
    if not 0 <= bitmap < (1 << REVOKE_BITMAP_WIDTH):
        raise ValueError(
            f"bitmap 0x{bitmap:x} does not fit CHIPLET_PUBK_REVOKE.select[7:0]; "
            f"bits 8 and above belong to the PQC and fused-key halves"
        )


def _bits_except(taken) -> Tuple[int, ...]:
    return tuple(b for b in range(REVOKE_BITMAP_WIDTH) if b not in taken)


def _inert_bits() -> Tuple[int, ...]:
    return tuple(b for b in range(REVOKE_BITMAP_WIDTH) if (1 << b) & INERT_BIT_MASK)


def _subset(rng: SepSeededRng, pool: Tuple[int, ...]) -> int:
    """A possibly empty random subset of ``pool``, as a bitmap."""
    if not pool:
        return 0
    mask = rng.getrandbits(len(pool))
    return sum(1 << bit for i, bit in enumerate(pool) if mask & (1 << i))


def _nonempty_subset(rng: SepSeededRng, pool: Tuple[int, ...]) -> int:
    """As :func:`_subset`, but never empty. Bounded: no rejection loop."""
    if not pool:
        raise ValueError("cannot draw a non-empty subset of an empty pool")
    value = _subset(rng, pool)
    if value == 0:
        value = 1 << pool[rng.randrange(len(pool))]
    return value


def _other_slot(rng: SepSeededRng, taken: int) -> int:
    choices = tuple(s for s in range(PUBK_SEL_NUM_ROM_KEYS) if s != taken)
    return choices[rng.randrange(len(choices))]


def _selftest() -> None:
    """Check exhaustively that the classifier, bins and draw agree at import time."""
    # Exhaustive over the whole stimulus space, not a sample: 256 x 6 x 6.
    seen = {c: 0 for c in CLASSES}
    known = set(all_bins())
    for bitmap in range(1 << REVOKE_BITMAP_WIDTH):
        for p in range(PUBK_SEL_NUM_ROM_KEYS):
            for b in range(PUBK_SEL_NUM_ROM_KEYS):
                cls = classify(bitmap, p, b)
                seen[cls] += 1
                outcome = outcome_of(cls)
                if bit_set(bitmap, p):
                    want = OUTCOME_TERMINAL if bit_set(bitmap, b) else OUTCOME_FAILOVER
                else:
                    want = OUTCOME_PROCEED
                if outcome != want:
                    raise RuntimeError(
                        f"classify(0x{bitmap:02x}, {p}, {b}) -> {cls} gives outcome "
                        f"{outcome}, but the two-boolean table says {want}"
                    )
                for name in coverage_bins(bitmap, p, b):
                    if name not in known:
                        raise RuntimeError(f"coverage_bins produced unknown bin {name}")
    if min(seen.values()) == 0:
        raise RuntimeError(f"some class is unreachable: {seen}")
    if len(all_bins()) != 27 or len(set(all_bins())) != 27:
        raise RuntimeError(f"closure set is {len(all_bins())} bins, expected 27 distinct")
    # The draw must land in the class it asked for, and must be reproducible.
    for seed in range(200):
        d = draw(seed)
        _check_bitmap(d.bitmap)
        if classify(d.bitmap, d.primary_slot, d.backup_slot) != d.expected_class:
            raise RuntimeError(f"seed {seed}: {d.describe()} does not classify as itself")
        if draw(seed) != d:
            raise RuntimeError(f"seed {seed}: draw() is not a pure function of the seed")


_selftest()
