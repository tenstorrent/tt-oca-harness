# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with a signed OCA BL1 demotion request (valid and enabled) -> ignored, both locked.

The ROM prints ``DEMOTE: PROD_END lock`` instead of ``BL1_DEMOTE=``, locks both DEMOTE
registers non-demoted, leaves FEAT_CTRL at the non-demoted profile and records no demotion
in the boot PCR. Needs ``+esrc_noise_force``: PROD_END enforces secure boot.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_30_prod_end_test(sep_demotion_prod_end_base):
    """PROD_END with BL1 valid/enabled: not demoted, both registers locked."""

    _SEL = 1
    _AUTH = 1
    _BL2 = 0
