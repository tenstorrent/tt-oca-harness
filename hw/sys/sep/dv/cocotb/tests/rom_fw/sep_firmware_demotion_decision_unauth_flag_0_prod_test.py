# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with no BL1 decision and signed OCA BL2 demotion requested.

The BL2 request is deferred and DEMOTE_1 remains unwritten and unlocked, so the
boot measurement carries demotion bits 0x4.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_bl2_request_prod_test(sep_demotion_prod_base):
    """A BL2-only OCA request under PROD leaves DEMOTE_1 unwritten."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 1

    demotion_required = ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=", "DEMOTE_NOT_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=1",)

    expect_demote_1 = (0, 0)
    expect_demote_2 = (0, 0)

    # (0, 0) is also the reset value, so require exactly one probe sample for the run.
    demote_changes_min = 1
    demote_changes_max = 1
