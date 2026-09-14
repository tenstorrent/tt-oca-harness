# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: rtl_placeholder, needs_dtp_csr_sub
Routing verification for the peripheral AXI-Lite external-macro windows. On
this DUT pll_wrap/pvt_wrap are OKAY+0 placeholder blocks and the smc_wrapper
DTP CSR port has no subordinate (its response is tied idle; SMU wires DTP
internally), so no routing behaviour exists to check.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_macro_axil_routing_test(smc_base_test):
    """Deferred: placeholder PLL/PVT wraps and an idle DTP CSR port."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_macro_axil_routing_test deferred: pll/pvt placeholder wraps and an "
            "idle smc_wrapper DTP CSR port (SMU wires DTP)."
        )
