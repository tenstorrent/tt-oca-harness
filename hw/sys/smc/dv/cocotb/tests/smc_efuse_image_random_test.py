# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse image-pattern leaf: random full-width fields and write locks from the leaf seed."""

from __future__ import annotations

import pyuvm
from smc_efuse_image_pattern_base import smc_efuse_image_pattern_base


@pyuvm.test()
class smc_efuse_image_random_test(smc_efuse_image_pattern_base):
    """Sense a random image; sweep, write, lock and re-sense every SMC_EFUSE_MAP word."""

    pattern = "random"
