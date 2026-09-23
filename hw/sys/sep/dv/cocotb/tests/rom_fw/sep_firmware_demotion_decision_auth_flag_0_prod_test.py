# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit 17 CLEAR, BL1 demotion flag set -> the flag is IGNORED.

Negative control: the manifest requests BL1 demotion without the selector bit, so a
ROM that reads the flag without testing the selector writes DEMOTE_1 demoted.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_test(sep_demotion_prod_base):
    """PROD, selector bit clear, BL1 flag set: request ignored, DEMOTE_1 (0, 1)."""

    _SEL = 0
    _AUTH = 1
    _BL2 = 0

    demotion_required = ("DEMOTE: BL2 deferred, lock non-demoted", "BL2_DEMOTE_DEC=",
                         "DEMOTE_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=0",)

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
