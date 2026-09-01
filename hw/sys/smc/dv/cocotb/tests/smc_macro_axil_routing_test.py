# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Routing verification for peripheral AXI-Lite external-macro windows — DEFERRED.

Exercises pll/pvt OKAY wraps and idle smc_wrapper DTP CSR port after TB
err_slv removal. Shelved until real adopter PLL/PVT IP and a legal
smc_wrapper DTP CSR subordinate exist (SMU already wires DTP; not this DUT).
See testlists/deferred.toml (rtl_placeholder / needs_dtp_csr_sub).
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_macro_axil_routing_test(smc_base_test):
    """Deferred: rtl_placeholder + needs_dtp_csr_sub."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_macro_axil_routing_test deferred: pll/pvt placeholder wraps "
            "and idle smc_wrapper DTP CSR (TB err_slv removed; SMU wires DTP). "
            "See testlists/deferred.toml."
        )
