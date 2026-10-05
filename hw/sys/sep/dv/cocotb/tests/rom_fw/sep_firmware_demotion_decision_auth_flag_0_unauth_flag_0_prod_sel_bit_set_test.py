# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID set, BOTH demotion flags set -> BL1 wins and locks.

Outcome O2b of the [S25] outcome table in ``sep_demotion_decision_base.py``; the shared PROD
stimulus is in ``sep_demotion_prod_base.py``. This is the precedence test: BL1_DEMOTION_ENABLE
asks BL0 to demote at once and the BL2 request asks to defer to BL2. In ``rom_main.c``
BL1_DEMOTION_VALID routes into the first arm, so ``demotion_reg`` takes BL1_DEMOTION_ENABLE and
``lock_demotion`` keeps its initialiser. The deferral arm is an ``else if`` and does not run.

A ROM that let the BL2 request reach ``lock_demotion`` (tested before BL1_DEMOTION_VALID, or
cleared the lock whenever the BL2 flag is set) produces ``DEMOTE_NOT_LOCKED`` and
``lcc_demote_lock_1_probe_o == 0`` (outcome O4). This member requires DEMOTE_1 = (1, 1),
``DEMOTE_LOCKED``, and forbids ``DEMOTE_NOT_LOCKED``. The O2a sibling leaves the BL2 request
clear, so nothing competes with BL1_DEMOTION_VALID there.

The console also prints ``BL2_DEMOTE_DEC=``, the value BL0 hands to BL1, so this member requires
``BL2_DEMOTE_DEC=1`` and forbids ``=0``; that separates its console from O2a's. No
``+esrc_noise_force``: secure boot is off.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_sel_bit_set_test(
    sep_demotion_prod_base
):
    """PROD, selector set, both flags set: DEMOTE_1 demoted and locked, BL2 dec 1."""

    _SEL = 1
    _AUTH = 1
    _BL2 = 1

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=1", "BL2_DEMOTE_DEC=1")

    # rom_main.c lc_write_demotion(demotion_reg=true, lock=true). The lock is
    # the load-bearing half here -- see the docstring. BL0 writes DEMOTE_2 only
    # at PROD_END.
    expect_demote_1 = (1, 1)
    expect_demote_2 = (0, 0)
