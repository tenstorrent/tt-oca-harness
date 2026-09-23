# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit 17 set, BOTH demotion flags set -> BL1 wins and locks.

Precedence test: the selector routes the ROM into the BL1 arm, so the BL2 deferral
flag must not clear the lock, and the console still reports ``BL2_DEMOTE_DEC=1``.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_sel_bit_set_test(
        sep_demotion_prod_base):
    """PROD, selector set, both flags set: DEMOTE_1 demoted and locked, BL2 dec 1."""

    _SEL = 1
    _AUTH = 1
    _BL2 = 1

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=1", "BL2_DEMOTE_DEC=1")

    expect_demote_1 = (1, 1)
    expect_demote_2 = (0, 0)
