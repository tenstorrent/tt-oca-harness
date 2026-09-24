# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Keep a random eFuse image from making post-sense FEAT_CTRL zero.

FEAT_CTRL is the INVERSE of the SIP_DIS / SYS_DIS disable vectors, so a draw
whose two vectors between them cover all sixteen Function bits collapses it to
zero. A test that proves fail-closed by contrast -- FEAT_CTRL reads 0 before
sense and its real value after -- then compares 0 against 0, and a DUT that
never opened the guard passes. About 1% of PROD and PROD_END draws land there.

This module repairs only that draw. The image is built exactly as the test
would build it, the resulting FEAT_CTRL is computed, and the vectors are
replaced ONLY if it came out zero; every other seed keeps the image it already
had. The replacement is drawn from the seed, so ``--seed N`` still replays.

Both the test and ``dv_sim_prestage`` call this, so the staged t=0 image and
the test's golden cannot disagree.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from sep_efuse_image import SepEfuseImage
from sep_lcc_golden import FUNC_MASK, feat_ctrl_expected
from sep_seeded_rng import SepSeededRng

# Separates the repair stream from the image stream, so the replacement bit
# does not track a value the image draw already consumed.
_REPAIR_SALT = 0x000F_EA7C

# Child of cocotb's logger so the line lands in the sim log; outside a sim
# (dv_sim_prestage) it simply has no handler, and the stage prints its own line.
_log = logging.getLogger("cocotb.sep_efuse_feat_ctrl")

__all__ = ["feat_ctrl_nonvacuous_fixed"]


def feat_ctrl_nonvacuous_fixed(
    seed: int, *, base: Optional[Dict[str, int]] = None
) -> Dict[str, int]:
    """``fixed=`` kwargs for ``randomize``/``select_efuse_image`` that cannot
    produce a zero post-sense FEAT_CTRL.

    Returns ``base`` unchanged on any seed whose natural draw already gives a
    non-zero FEAT_CTRL, which is the overwhelming majority.
    """
    base = dict(base or {})
    img = SepEfuseImage().randomize(seed, fixed=base)
    lc = img.lc_raw()
    sip = img.field_int("SIP_DIS")
    sys_dis = img.field_int("SYS_DIS")

    if feat_ctrl_expected(lc, sip, sys_dis) != 0:
        return base

    # Degenerate draw. Enable one Function feature in BOTH vectors -- both bind
    # in the states that can reach zero (TEST_DEV, PROD, PROD_END all read
    # ~(SIP|SYS)), so clearing the bit in one alone would not lift FEAT_CTRL.
    rng = SepSeededRng(seed ^ _REPAIR_SALT)
    bit = 48 + rng.randrange(16)
    sip &= ~(1 << bit)
    sys_dis &= ~(1 << bit)

    assert feat_ctrl_expected(lc, sip, sys_dis) & FUNC_MASK, (
        f"feat_ctrl repair failed for seed {seed}: lc_raw=0x{lc:x} "
        f"SIP_DIS=0x{sip:016x} SYS_DIS=0x{sys_dis:016x} still gives FEAT_CTRL=0"
    )
    base.update({"SIP_DIS": sip, "SYS_DIS": sys_dis})
    # Say so. The image this seed now produces is NOT the one a plain
    # randomize(seed) gives, and without this line a repaired run looks like an
    # ordinary one to anyone reproducing it.
    _log.info(
        "[efuse] seed %d drew SIP_DIS|SYS_DIS covering every Function bit, so "
        "post-sense FEAT_CTRL would be 0 and the fail-closed contrast vacuous; "
        "enabled bit %d in both vectors -> SIP_DIS=0x%016x SYS_DIS=0x%016x "
        "(FEAT_CTRL=0x%016x)",
        seed, bit, sip, sys_dis, feat_ctrl_expected(lc, sip, sys_dis),
    )
    return base
