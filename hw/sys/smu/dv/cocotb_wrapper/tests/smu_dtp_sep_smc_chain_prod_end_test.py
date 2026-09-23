# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_sep_smc_chain_prod_end_test - one image of the smu_dtp_sep_smc_chain_test body.

PROD_END image: the same firmware and JTAG operation, but the demote changes nothing and the bridge must launch nothing.
The testlist entry supplies the preload image and the contract plusargs; the
body in `smu_dtp_sep_smc_chain_test.py` runs them.
"""

from __future__ import annotations

import pyuvm
from smu_dtp_sep_smc_chain_test import smu_dtp_sep_smc_chain_test


@pyuvm.test()
class smu_dtp_sep_smc_chain_prod_end_test(smu_dtp_sep_smc_chain_test):
    """PROD_END image."""
