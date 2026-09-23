# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit CLEAR, BL2 demotion requested -> DEMOTE_1 left UNWRITTEN.

The ROM defers the decision to BL2, leaves DEMOTE_1 unwritten and does not lock it;
the BL1 demotion flag is also set and must be ignored.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_test(
        sep_demotion_prod_base):
    """PROD, selector clear, BL2 flag set: deferral unlocked, DEMOTE_1 unwritten."""

    _SEL = 0
    _AUTH = 1
    _BL2 = 1

    demotion_required = ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=",
                         "DEMOTE_NOT_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=1",)

    expect_demote_1 = (0, 0)
    expect_demote_2 = (0, 0)

    # (0, 0) is also the reset value, so require exactly one probe sample for the run.
    demote_changes_min = 1
    demote_changes_max = 1
