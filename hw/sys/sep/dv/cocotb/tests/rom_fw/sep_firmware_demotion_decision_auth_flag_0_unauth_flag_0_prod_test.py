# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID clear, BL2 demotion requested -> DEMOTE_1 left UNWRITTEN.

Outcome O4 of the [S25] outcome table in ``sep_demotion_decision_base.py``; the shared PROD
stimulus is in ``sep_demotion_prod_base.py``. This is the only outcome where ``lock_demotion``
goes false in ``rom_main.c``, ``DEMOTE_NOT_LOCKED`` replaces ``DEMOTE_LOCKED``, and the deferred
``lc_write_demotion`` does not run, so DEMOTE_1 stays at its reset value. ``+AUTH_FLAG_0`` is also
set and is ignored, as in the O5 sibling: BL1_DEMOTION_VALID is clear, so BL1_DEMOTION_ENABLE is
never consulted and the BL2 request alone decides.

``expect_demote_1 = (0, 0)`` is also the reset value, so the member pins the probe sample count
exactly (``demote_changes_min = demote_changes_max = 1``): the monitor records the reset sample
and nothing else for the whole run. O4 leaves ``lock == 0``, so the register stays writeable by
later software; the exact count covers BL1 (``dv/fw/tests/bl1_pass_test/bl1_pass_test.c``) too.

With both registers unwritten, this member alone cannot prove the LOCK probes are live. The
``state`` rails are differential (``{~demote, demote}``) and ``_decode_demote`` raises on
``0b00``, so a dead state probe fails. The O2b sibling drives ``lk1`` 0 -> 1 and the PROD_END
members drive ``lk2`` 0 -> 1 through the same wiring. No ``+esrc_noise_force``: secure boot is
off.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_test(sep_demotion_prod_base):
    """PROD, selector clear, BL2 flag set: deferral unlocked, DEMOTE_1 unwritten."""

    # OCAH plusargs: +LC_STATE_PROD +AUTH_FLAG_0 +UNAUTH_FLAG_0, no
    # +SET_SELECTOR_BIT_17.
    _SEL = 0
    _AUTH = 1
    _BL2 = 1

    demotion_required = ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=", "DEMOTE_NOT_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=1",)

    # Neither register is written: lock_demotion is false, so the deferred
    # lc_write_demotion() does not run, and lc_write_demotion_2() runs only at
    # PROD_END. Both read their reset value (0, 0).
    expect_demote_1 = (0, 0)
    expect_demote_2 = (0, 0)

    # The whole simulation must contain exactly ONE probe sample -- the reset one.
    # See the docstring: this is what makes "never written" an observation rather
    # than a value that happens to match, and it covers BL1's execution too.
    demote_changes_min = 1
    demote_changes_max = 1
