# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_efuse_map_sense_image_test at the walking eFuse image.

The module fixes the image kind; the testlist entry carries the matching run argument.
"""

from __future__ import annotations

import pyuvm
from smc_efuse_map_sense_image_test import smc_efuse_map_sense_image_test


@pyuvm.test()
class smc_efuse_map_sense_image_walking_test(smc_efuse_map_sense_image_test):
    """smc_efuse_map_sense_image_test at the walking eFuse image."""

    KIND = "walking"
    required_evidence = (
        "CHK-EMAP-SENSE-DONE-ONCE",
        "CHK-EMAP-SENSE-FIRST-DONE",
        "CHK-EMAP-SENSE-PATTERNS",
        "CHK-EMAP-SHADOW-OUT-SENSED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
