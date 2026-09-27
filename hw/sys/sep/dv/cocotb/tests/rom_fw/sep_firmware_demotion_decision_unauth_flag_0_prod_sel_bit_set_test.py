# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with BL1 valid/disabled and BL2 requested -> BL1 wins, not demoted.

Only the signed OCA BL1 decision may reach DEMOTE_1: a ROM that ORs the two
requests or falls through to the BL2 arm fails.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base

# Bit 2 carries the BL2 request, although measurement.h names it the BL2 decision.
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"


@pyuvm.test()
class sep_firmware_demotion_bl1_disable_over_bl2_request_prod_test(sep_demotion_prod_base):
    """BL1 valid/disabled overrides a BL2 request under PROD."""

    required_markers = sep_demotion_prod_base.required_markers + (_MEAS_LOCKED_BL2_COUNTED,)
    forbidden_markers = sep_demotion_prod_base.forbidden_markers + (_MEAS_LOCKED_BL2_ABSENT,)

    _SEL = 1
    _AUTH = 0
    _BL2 = 1

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=1")

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
