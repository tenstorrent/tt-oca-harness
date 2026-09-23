# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit 17 set, BL1 flag clear, BL2 flag SET -> BL1 wins, not demoted.

Only the BL1 flag may reach DEMOTE_1: a ROM that ORs the two flags or falls through
to the BL2 arm fails, and the BL2 request must still be echoed and measured.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base

# Bit 2 carries the BL2 request, although measurement.h names it the BL2 decision.
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_0_prod_sel_bit_set_test(
        sep_demotion_prod_base):
    """PROD, selector set, BL1 flag clear, BL2 flag set: not demoted but locked."""

    required_markers = sep_demotion_prod_base.required_markers + (
        _MEAS_LOCKED_BL2_COUNTED,
    )
    forbidden_markers = sep_demotion_prod_base.forbidden_markers + (
        _MEAS_LOCKED_BL2_ABSENT,
    )

    _SEL = 1
    _AUTH = 0
    _BL2 = 1

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=1")

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
