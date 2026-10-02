# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse image-pattern leaf: every field 0xAAAA..., no write lock set."""

from __future__ import annotations

import pyuvm
from smc_efuse_image_pattern_base import smc_efuse_image_pattern_base


@pyuvm.test()
class smc_efuse_image_altaa_test(smc_efuse_image_pattern_base):
    """Sense a altaa image; sweep, write, lock and re-sense every SMC_EFUSE_MAP word."""

    pattern = "altaa"
