# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with a BL2 demotion REQUEST pending -> the request is ignored, locked.

A ROM that reads ``flag_args`` bit 0 before the lifecycle leaves DEMOTE_1 unlocked
and prints ``MEAS_DEMOTE=0x00000006``. Needs ``+sep_crypto_edn_force``.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base

_MEAS_LOCK_ONLY = "MEAS_DEMOTE=0x00000002"
_MEAS_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_0_prod_end_test(
        sep_demotion_prod_end_base):
    """PROD_END with flag_args[0] set: the BL2 request is dropped, both locked."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 1

    required_markers = sep_demotion_prod_end_base.required_markers + (
        _MEAS_LOCK_ONLY, "PLD_HASH_OK",
    )
    forbidden_markers = sep_demotion_prod_end_base.forbidden_markers + (
        _MEAS_BL2_COUNTED, "PLD_HASH_FAIL=",
    )
