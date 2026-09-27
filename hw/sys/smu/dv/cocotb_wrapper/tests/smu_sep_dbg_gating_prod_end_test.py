# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_dbg_gating_prod_end_test - one image of the smu_sep_dbg_gating_test body.

PROD_END image: dbg_disable must gate the SMC fabric JTAG2AXI bridge, not merely assert.
The testlist entry supplies the preload image and the contract plusargs; the
body in `smu_sep_dbg_gating_test.py` runs them.
"""

from __future__ import annotations

import pyuvm
from smu_sep_dbg_gating_test import smu_sep_dbg_gating_test


@pyuvm.test()
class smu_sep_dbg_gating_prod_end_test(smu_sep_dbg_gating_test):
    """PROD_END image."""
