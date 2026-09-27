# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with signed OCA BL2 demotion requested -> ignored and locked.

A ROM that consumes ``demotion_control`` before applying the lifecycle rule leaves
DEMOTE_1 unlocked and prints ``MEAS_DEMOTE=0x00000006``.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base

_MEAS_LOCK_ONLY = "MEAS_DEMOTE=0x00000002"
_MEAS_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"


@pyuvm.test()
class sep_firmware_demotion_bl2_request_prod_end_test(sep_demotion_prod_end_base):
    """PROD_END drops the OCA BL2 request and locks both demotion registers."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 1

    required_markers = sep_demotion_prod_end_base.required_markers + (
        _MEAS_LOCK_ONLY,
        "PLD_HASH_OK",
    )
    forbidden_markers = sep_demotion_prod_end_base.forbidden_markers + (
        _MEAS_BL2_COUNTED,
        "PLD_HASH_FAIL=",
    )
