# SPDX-License-Identifier: Apache-2.0
"""SMC OSS Cadence I3C AXIL probe — DEFERRED.

Needs real I3C DAT/DCT and/or non-placeholder I3C AXIL path. See
testlists/deferred.toml and testlists/deferred.toml.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cdns_i3c_axil_test(smc_base_test):
    """Deferred: needs_i3c_dat_dct / rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_cdns_i3c_axil_test deferred: I3C DAT/DCT TB ram removed and "
            "Cadence AXIL path is placeholder-backed. "
            "See testlists/deferred.toml."
        )
