# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit 17 set, BL1 demotion flag CLEAR -> not demoted, locked.

The ROM copies the clear BL1 flag into DEMOTE_1 and still locks it; only the lock
probe, not the console, can show that the register was written.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_sel_bit_set_test(
        sep_demotion_prod_base):
    """PROD, selector set, BL1 flag clear: DEMOTE_1 not demoted but locked."""

    _SEL = 1
    _AUTH = 0
    _BL2 = 0

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=0")

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
