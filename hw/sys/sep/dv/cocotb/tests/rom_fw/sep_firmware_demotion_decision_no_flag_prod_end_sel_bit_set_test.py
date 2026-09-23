# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END + selector bit 17 set -> the selector is PREEMPTED, both locked.

Checks the short-circuit order: a ROM that tests the selector before the lifecycle
prints ``BL1_DEMOTE=`` and leaves DEMOTE_2 unwritten. Needs ``+sep_crypto_edn_force``.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_end_sel_bit_set_test(
        sep_demotion_prod_end_base):
    """PROD_END with selector bit 17 set: the selector is never consulted."""

    _SEL = 1
    _AUTH = 0
    _BL2 = 0
