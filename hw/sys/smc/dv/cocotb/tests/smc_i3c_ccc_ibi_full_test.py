# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: needs_i3c_dat_dct
I3C directed-SDR protocol test. This bench instantiates no I3C DAT/DCT backing
memory (no-placeholder policy), so the scenario has no target to run against.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_ccc_ibi_full_test(smc_base_test):
    """Deferred: no I3C DAT/DCT backing memory in this bench."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_i3c_ccc_ibi_full_test deferred: this bench instantiates no I3C DAT/DCT "
            "backing memory."
        )
