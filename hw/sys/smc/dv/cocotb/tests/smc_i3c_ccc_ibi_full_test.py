# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM I3C directed-SDR protocol test — DEFERRED.

TB I3C DAT/DCT prim_ram removed (no-placeholder policy). Re-enable when real
DAT/DCT macros (or product-backed mem) are present. See
testlists/deferred.toml (needs_i3c_dat_dct).
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_ccc_ibi_full_test(smc_base_test):
    """Deferred: needs real I3C DAT/DCT (TB ram removed)."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_i3c_ccc_ibi_full_test deferred: TB I3C DAT/DCT removed. "
            "See testlists/deferred.toml (needs_i3c_dat_dct)."
        )
