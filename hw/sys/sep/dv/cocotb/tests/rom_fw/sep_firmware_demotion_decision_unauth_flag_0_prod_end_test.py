# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with signed OCA BL2 demotion requested -> ignored and locked.

A ROM that consumes ``demotion_control`` before applying the lifecycle rule leaves
DEMOTE_1 unlocked and records the BL2 decision in the boot measurement, which the
base's ``BL0S_BOOT_PCR=`` check refuses.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_bl2_request_prod_end_test(sep_demotion_prod_end_base):
    """PROD_END drops the OCA BL2 request and locks both demotion registers."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 1
