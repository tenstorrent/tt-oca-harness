# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle demote product config: LC x DEMOTE_1/2 x a small DIS subset.

RAND-REP. Discrete cells are walked every seed. DIS vectors are W1S-compatible
so one OTP image can carry both: all-zero first, then the pinned non-zero pair.
Demote is write-once-set; a resense (rst_ni pulse) returns the CSRs to 0 so
each LC can walk (0,0), (1,0), (0,1), (1,1). After that walk the same vehicle
locks one seed-selected DEMOTE register, proves a later demote write is
ignored, and that rst_ni releases the lock.
"""

from __future__ import annotations

from env.sep_lcc_golden import (
    DBG1_MASK,
    DBG2_MASK,
    LC_PROD,
    LC_TEST_DEV,
    SEP_FUSE_DBG_BIT,
    SMC_FUSE_DBG_BIT,
)
from env.sep_seeded_rng import SepSeededRng

# Distinct non-zero disable vectors so decoded FEAT_CTRL differs per cell.
# The pinned pair stays small (a few W1S bits) so the second DIS cell is
# reachable from DIS=0 in one OTP image.
DIS_ZERO = (0, 0)
# Close the named fuse-dbg bits while the DTP cases can still be open
# (PROD + both demotes, sep_debug still 1). Required discrete cell.
FUSE_DBG_DIS_MASK = (1 << SEP_FUSE_DBG_BIT) | (1 << SMC_FUSE_DBG_BIT)

LC_WALK = (LC_TEST_DEV, LC_PROD)


def _bit_span(mask: int) -> tuple[int, int]:
    """(lsb, msb + 1) of a contiguous group mask."""
    lsb = (mask & -mask).bit_length() - 1
    top = mask.bit_length()
    assert mask == ((1 << top) - 1) ^ ((1 << lsb) - 1), f"mask 0x{mask:x} is not contiguous"
    return lsb, top


# Disable-vector groups, lifecycle_controller.adoc: DBG_1 is [23:0] and DBG_2 is
# [47:24]. The DBG_1 extra bit starts above bit 0 (sep_debug), which the pinned
# pair sets on its own in SIP_DIS.
DBG1_SPAN = _bit_span(DBG1_MASK)
DBG2_SPAN = _bit_span(DBG2_MASK)
EXTRA_DBG1_RANGE = (DBG1_SPAN[0] + 1, DBG1_SPAN[1])
EXTRA_DBG2_RANGE = DBG2_SPAN


class SepLccDemoteMatrixCfg:
    """Single source of truth for the demote product walk."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        # Continuous knobs: which extra DIS bit (already covered by the pinned
        # pair) is logged so two seeds are not identical silent copies.
        self.extra_dbg1_bit = rng.randrange(*EXTRA_DBG1_RANGE)
        self.extra_dbg2_bit = rng.randrange(*EXTRA_DBG2_RANGE)
        # Which DEMOTE_{1,2} register carries the lock-slice proof this seed.
        self.lock_group = rng.choice((1, 2))
        self.lc_states = LC_WALK
        self.dis_zero = DIS_ZERO
        extra = (1 << self.extra_dbg1_bit) | (1 << self.extra_dbg2_bit)
        # SIP_DIS bit 0 disables sep_debug unless TEST_DEV demote_1 forces it.
        self.dis_fuse_dbg = (FUSE_DBG_DIS_MASK, FUSE_DBG_DIS_MASK)
        self.dis_pinned = (extra | FUSE_DBG_DIS_MASK | 0x1, extra | FUSE_DBG_DIS_MASK)

    def summary(self) -> str:
        return (
            f"seed={self.seed} lc={self.lc_states} "
            f"dis_zero={self.dis_zero} dis_fuse_dbg="
            f"(0x{self.dis_fuse_dbg[0]:x},0x{self.dis_fuse_dbg[1]:x}) "
            f"dis_pinned="
            f"(0x{self.dis_pinned[0]:016x},0x{self.dis_pinned[1]:016x}) "
            f"extra_dbg1_bit={self.extra_dbg1_bit} extra_dbg2_bit={self.extra_dbg2_bit} "
            f"lock_group={self.lock_group}"
        )

    def n_cells(self) -> int:
        # TEST_DEV+PROD at DIS=0 (8), PROD compose cell for bits 2/3 (1),
        # and PROD at the pinned DIS (4).
        return 13


def _selftest() -> None:
    assert DBG1_SPAN == (0, 24), DBG1_SPAN
    assert DBG2_SPAN == (24, 48), DBG2_SPAN
    for seed in range(64):
        cfg = SepLccDemoteMatrixCfg(seed)
        assert (1 << cfg.extra_dbg1_bit) & DBG1_MASK and cfg.extra_dbg1_bit != 0
        assert (1 << cfg.extra_dbg2_bit) & DBG2_MASK, cfg.extra_dbg2_bit


_selftest()
