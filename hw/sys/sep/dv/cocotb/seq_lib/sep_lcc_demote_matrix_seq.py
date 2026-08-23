# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle demote product config: LC x DEMOTE_1/2 x a small DIS subset.

RAND-REP. Discrete cells are walked every seed. DIS vectors are W1S-compatible
so one OTP image can carry both: all-zero first, then the pinned non-zero pair.
Demote is write-once-set; a resense (rst_ni pulse) returns the CSRs to 0 so
each LC can walk (0,0), (1,0), (0,1), (1,1).
"""

from __future__ import annotations

from env.sep_lcc_golden import LC_PROD, LC_TEST_DEV
from env.sep_seeded_rng import SepSeededRng

# Distinct non-zero disable vectors so decoded FEAT_CTRL differs per cell.
# The pinned pair stays small (a few W1S bits) so the second DIS cell is
# reachable from DIS=0 in one OTP image.
DIS_ZERO = (0, 0)

LC_WALK = (LC_TEST_DEV, LC_PROD)


class SepLccDemoteMatrixCfg:
    """Single source of truth for the demote product walk."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        # Continuous knobs: which extra DIS bit (already covered by the pinned
        # pair) is logged so two seeds are not identical silent copies.
        self.extra_dbg1_bit = rng.randrange(1, 16)
        self.extra_dbg2_bit = rng.randrange(16, 32)
        self.lc_states = LC_WALK
        self.dis_zero = DIS_ZERO
        extra = (1 << self.extra_dbg1_bit) | (1 << self.extra_dbg2_bit)
        # SIP_DIS bit 0 disables sep_debug unless TEST_DEV demote_1 forces it.
        self.dis_pinned = (extra | 0x1, extra)

    def summary(self) -> str:
        return (
            f"seed={self.seed} lc={self.lc_states} "
            f"dis_zero={self.dis_zero} dis_pinned="
            f"(0x{self.dis_pinned[0]:016x},0x{self.dis_pinned[1]:016x}) "
            f"extra_dbg1_bit={self.extra_dbg1_bit} extra_dbg2_bit={self.extra_dbg2_bit}"
        )

    def n_cells(self) -> int:
        # TEST_DEV+PROD at DIS=0 (8) and PROD at the pinned DIS (4).
        return 12
